"""HOST-only validation of a fixed 32 KiB primary GPT capture.

This module never opens hardware or writes an image. It validates primary header
and entry-array CRCs plus bounds; it cannot verify the remote backup GPT copy or
the actual media capacity from a primary capture alone.
Reference: https://uefi.org/specs/UEFI/2.10/05_GUID_Partition_Table_Format.html
"""
import argparse
import hashlib
import json
import pathlib
import struct
import uuid
import zlib

CAPTURE_BYTES = 0x8000
SECTOR = 512
HEADER = struct.Struct('<8sIIIIQQQQ16sQIII')


class InvalidGPT(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise InvalidGPT(message)


def crc32(data):
    return zlib.crc32(data) & 0xffffffff


def parse_primary(raw, expected_disk_bytes=None):
    if type(raw) is not bytes:
        raise TypeError('an immutable bytes capture is required')
    require(len(raw) == CAPTURE_BYTES, 'capture must contain exactly 32768 bytes')
    fields = HEADER.unpack_from(raw, SECTOR)
    (signature, revision, size, header_crc, reserved, current_lba, backup_lba,
     first_usable, last_usable, disk_guid, entries_lba, count, entry_size, array_crc) = fields
    require(signature == b'EFI PART' and revision == 0x00010000, 'unsupported GPT signature/revision')
    require(HEADER.size <= size <= SECTOR and reserved == 0, 'invalid GPT header size/reserved field')
    header = bytearray(raw[SECTOR:SECTOR + size])
    header[16:20] = bytes(4)
    require(crc32(header) == header_crc, 'primary header CRC mismatch')
    require(current_lba == 1 and backup_lba > last_usable >= first_usable >= 3,
            'invalid primary/backup/usable LBA bounds')
    require(disk_guid != bytes(16), 'empty disk GUID')
    require(1 <= count <= 128 and entry_size == 128, 'unsupported P011 GPT entry dimensions')
    entries_size = count * entry_size
    start = entries_lba * SECTOR
    end = start + entries_size
    require(entries_lba >= 2 and SECTOR * 2 <= start < end <= len(raw),
            'entry array lies outside fixed capture')
    array_sectors = (entries_size + SECTOR - 1) // SECTOR
    require(entries_lba + array_sectors <= first_usable and
            last_usable < backup_lba - array_sectors, 'GPT structures overlap usable LBAs')
    reported_disk_bytes = (backup_lba + 1) * SECTOR
    if expected_disk_bytes is not None:
        require(type(expected_disk_bytes) is int and expected_disk_bytes > 0 and
                expected_disk_bytes % SECTOR == 0, 'invalid external media capacity')
        require(reported_disk_bytes == expected_disk_bytes, 'GPT capacity differs from external capacity')
    require(crc32(raw[start:end]) == array_crc, 'primary entry-array CRC mismatch')
    names, identifiers, parts = set(), set(), []
    for index in range(count):
        entry = raw[start + index * entry_size:start + (index + 1) * entry_size]
        type_guid, unique_guid = entry[:16], entry[16:32]
        if type_guid == bytes(16):
            continue
        first, last, attributes = struct.unpack_from('<QQQ', entry, 32)
        require(first_usable <= first <= last <= last_usable,
                'partition %d lies outside usable LBAs' % (index + 1))
        require(unique_guid != bytes(16) and unique_guid not in identifiers,
                'empty or duplicate unique partition GUID')
        identifiers.add(unique_guid)
        try:
            padded_name = entry[56:128].decode('utf-16-le', 'strict')
        except UnicodeDecodeError as exc:
            raise InvalidGPT('invalid UTF-16 partition name') from exc
        name, separator, padding = padded_name.partition('\0')
        require(name and not any(ord(c) < 32 for c in name) and
                (not separator or not padding.strip('\0')), 'empty/control/nonzero-padded partition name')
        require(name not in names, 'duplicate partition name')
        names.add(name)
        parts.append(dict(index=index + 1, name=name,
                          type_guid=str(uuid.UUID(bytes_le=type_guid)),
                          unique_guid=str(uuid.UUID(bytes_le=unique_guid)),
                          first_lba=first, last_lba=last, attributes=attributes,
                          offset_bytes=first * SECTOR, size_bytes=(last - first + 1) * SECTOR))
    require(parts, 'no defined partitions')
    ordered = sorted(parts, key=lambda p: p['first_lba'])
    for before, after in zip(ordered, ordered[1:]):
        require(before['last_lba'] < after['first_lba'], 'overlapping partition ranges')
    return dict(status='PRIMARY_GPT_VALIDATED_OFFLINE', capture_bytes=len(raw),
                capture_sha256=hashlib.sha256(raw).hexdigest(), sector_bytes=SECTOR,
                primary_header_crc_verified=True, primary_array_crc_verified=True,
                backup_gpt_verified=False, media_capacity_independently_verified=expected_disk_bytes is not None,
                reported_disk_bytes=reported_disk_bytes, disk_guid=str(uuid.UUID(bytes_le=disk_guid)),
                first_usable_lba=first_usable, last_usable_lba=last_usable,
                backup_header_lba=backup_lba, partition_count=len(parts), partitions=parts,
                adb_invoked=False, hardware_accessed=False, image_modified=False,
                limitation='Primary capture does not establish firmware identity, write permission, or recovery.')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Validate an existing 32KiB primary GPT capture offline')
    parser.add_argument('capture', type=pathlib.Path)
    parser.add_argument('--expected-disk-bytes', type=int)
    args = parser.parse_args(argv)
    path = args.capture.resolve(strict=True)
    require(path.is_file() and not args.capture.is_symlink(), 'capture must be a regular non-link file')
    require(path.stat().st_size == CAPTURE_BYTES, 'capture file size is not 32768')
    print(json.dumps(parse_primary(path.read_bytes(), args.expected_disk_bytes), indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
