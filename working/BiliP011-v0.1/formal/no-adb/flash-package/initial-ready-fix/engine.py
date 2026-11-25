"""Bounded native Windows AutoD storage transport; no ADB or external FDL."""
import array
import ctypes
import gzip
import hashlib
import json
import pathlib
import struct
import sys
import time

import storage_read_codec as codec
import win32_download_transport as win

SIZES = {'user_partition': 32768, 'uboot': 1048576, 'miscdata': 1048576,
         'uboot_log': 4194304, 'prodnv': 10485760, 'system': 1073741824}
STEP = 4096
MODE = bytes.fromhex('7e000000000800fe827e')


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def checksum(data, direction='TX'):
    words = array.array('H')
    words.frombytes(data[:len(data) & ~1])
    if sys.byteorder != 'little':
        words.byteswap()
    total = sum(words) + (data[-1] if len(data) & 1 else 0)
    total = (total >> 16) + (total & 65535)
    total += total >> 16
    total = ~total & 65535
    if not len(data) & 1 or direction == 'RX':
        total = (total >> 8) | ((total & 255) << 8)
    return total


def packet(code, data=b''):
    require(code in (0x10, 0x11, 0x12, 1, 2, 3) and len(data) <= STEP, 'unsupported storage request')
    body = struct.pack('>HH', code, len(data)) + data
    return b'\x7e' + body + struct.pack('>H', checksum(body)) + b'\x7e'


def select(code, name):
    require(name in SIZES and (code == 0x10 or (code == 1 and name == 'system')), 'unsupported partition')
    return packet(code, name.encode('utf-16-le').ljust(72, b'\0') + struct.pack('<I', SIZES[name]))


def sha_file(path):
    digest = hashlib.sha256()
    with pathlib.Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def target(rows):
    require(len(rows) == 1, '只能连接一支 P011，且必须处于下载接口。')
    row = rows[0]
    require(row['pid'] == '4D00' and row['started'] and row['problem'] == 0 and row['port'],
            '下载驱动未就绪：请安装设备厂商提供的签名 SPRD 下载驱动。')
    return row


class Session:
    def __init__(self, folder):
        self.folder = pathlib.Path(folder)
        self.serial = self.node = None
        self.failed = False
        self.attempts = 0
        self.last_identity_check = 0
        self.tx = gzip.open(self.folder / 'wire.tx.raw.gz', 'xb', compresslevel=1)
        self.rx = gzip.open(self.folder / 'wire.rx.raw.gz', 'xb', compresslevel=1)
        self.events = gzip.open(self.folder / 'wire.events.jsonl.gz', 'xt', encoding='utf-8', compresslevel=1)
        self.state = dict(mode_attempts=0, sync_attempts=0, open_attempts=0,
                          adb_invoked=False, external_loader_uploaded=False,
                          write_started=False, write_bytes_acked=0, write_end_ack=False,
                          host_handle_closed=True, protocol_retry=False)

    def event(self, kind, **fields):
        self.events.write(json.dumps(dict(kind=kind, monotonic=time.monotonic(), **fields)) + '\n')

    def close_handle(self):
        if self.serial is not None:
            self.serial.close()
            self.serial = None
            self.state['host_handle_closed'] = True

    def open(self, node):
        self.state['open_attempts'] += 1
        require(self.state['open_attempts'] <= 2, '串口打开次数超限。')
        self.node = node
        self.serial = win.open_download(node)
        self.state['host_handle_closed'] = False
        self.last_identity_check = 0

    def ensure_identity(self, force=False):
        if force or time.monotonic() - self.last_identity_check >= .25:
            win._current_exact(win._identity(self.node))
            self.last_identity_check = time.monotonic()

    def send_once(self, raw, label, force_identity=False):
        require(not self.failed, '先前请求失败，禁止重试。')
        self.ensure_identity(force_identity)
        require(self.serial.pending() == 0, '存在未处理的串口数据，已停止。')
        if label == 'MODE':
            require(self.state['mode_attempts'] == 0, 'MODE 已发送，禁止重发。')
            self.state['mode_attempts'] += 1
        if label == 'SYNC_CRC':
            require(self.state['sync_attempts'] == 0, 'SYNC 已发送，禁止重发。')
            self.state['sync_attempts'] += 1
        self.attempts += 1
        self.event('ATTEMPT', number=self.attempts, label=label, bytes=len(raw))
        self.tx.write(raw)
        self.tx.flush()
        buffer, written = ctypes.create_string_buffer(raw), win.DWORD()
        if not self.serial._api.WriteFile(self.serial._handle_open(), buffer, len(raw), ctypes.byref(written), None):
            self.failed = True
            raise win._win_error()
        if written.value != len(raw):
            self.failed = True
            raise RuntimeError('串口部分写入：已停止，不重发。')

    def exchange(self, raw, label, mode=codec.SUM16, escaped=False, expected_type=0x80, expected_size=0):
        try:
            self.send_once(raw, label, force_identity=expected_size == 0)
            data = bytearray()
            decoder = codec.Decoder(mode, codec.ESCAPED) if escaped else None
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                block = self.serial.read_available()
                if not block:
                    time.sleep(.001)
                    continue
                self.rx.write(block)
                data.extend(block)
                require(len(data) <= 2 * (STEP + 8), '应答超出长度上限。')
                if decoder is not None:
                    frames = decoder.feed(block)
                    if not frames:
                        continue
                    complete = decoder.finish()
                    require(len(complete) == 1, '应答数异常。')
                    code, payload = complete[0].packet_type, complete[0].payload
                else:
                    require(data[0] == 0x7e, '应答头错误。')
                    if len(data) < 5:
                        continue
                    code, size = struct.unpack_from('>HH', data, 1)
                    require(size <= STEP, '应答载荷过长。')
                    if len(data) < size + 8:
                        continue
                    require(len(data) == size + 8 and data[-1] == 0x7e, '应答长度或边界异常。')
                    require(checksum(data[1:-3], 'RX') == int.from_bytes(data[-3:-1], 'big'), '应答校验失败。')
                    payload = bytes(data[5:-3])
                require(code == expected_type and len(payload) == expected_size,
                        '设备拒绝或应答异常：0x%04x，长度 %d' % (code, len(payload)))
                self.event('RESPONSE', number=self.attempts, bytes=len(data), code=code)
                return payload
            raise RuntimeError('设备应答超时：已停止，不重发。')
        except BaseException:
            self.failed = True
            self.rx.flush()
            self.events.flush()
            raise

    def wait_mode_reenumeration(self, timeout=30):
        """Observe only: never send/reopen until the old boot node has left."""
        require(self.serial is None and self.state['mode_attempts'] == 1 and
                self.state['sync_attempts'] == 0 and not self.state['write_started'],
                '只允许在单次 MODE 后、SYNC 前等待重枚举。')
        previous = win._identity(self.node)
        deadline = time.monotonic() + timeout
        transitioned = False
        stable_since = None
        stable_identity = None
        last_snapshot = None
        print('已发送模式切换，正在等待同一设备重新枚举下载接口（最多30秒）。', flush=True)
        self.state['phase'] = 'WAIT_MODE_REENUMERATION'
        while time.monotonic() < deadline:
            try:
                rows = win.inventory()
            except win.TransportRefusal as exc:
                if str(exc) != 'PnP status unavailable (CONFIGRET 13)':
                    raise
                # Incomplete PnP data is not proof that the old device left.
                rows = None
            snapshot = None if rows is None else [(r.get('pid'), r.get('port'), r.get('devinst'),
                r.get('started'), r.get('problem'), hashlib.sha256(r.get('id', '').encode()).hexdigest()) for r in rows]
            if snapshot != last_snapshot:
                self.event('MODE_PNP_SNAPSHOT', nodes=snapshot)
                last_snapshot = snapshot
            if rows is None:
                stable_since = stable_identity = None
            elif not rows:
                transitioned = True
                stable_since = stable_identity = None
            else:
                require(not any(r.get('pid') == '4064' for r in rows),
                        '模式切换后设备进入正常系统，已停止；请关机拔线后重新运行。')
                require(len(rows) == 1 and rows[0].get('pid') == '4D00',
                        '模式切换期间发现多个或未知接口，已停止。')
                row = rows[0]
                require(row.get('id') == previous[0], '模式切换后 USB 设备身份变化，已停止。')
                if row.get('devinst') != previous[1]:
                    transitioned = True
                if row.get('started') is not True or row.get('problem') != 0 or not row.get('port'):
                    stable_since = stable_identity = None
                elif transitioned:
                    identity = win._identity(row)
                    if identity != stable_identity:
                        stable_identity, stable_since = identity, time.monotonic()
                    elif time.monotonic() - stable_since >= .2:
                        self.event('MODE_REENUMERATION_READY', port=row['port'], devinst=row['devinst'])
                        return row
            time.sleep(.03)
        raise RuntimeError('等待模式切换后的下载接口重枚举超时；未发送 SYNC 或分区命令，请保留日志。')

    def wait_initial_ready(self, wait_seconds=300, readiness_seconds=3):
        """Observe the new unique node until Windows has started its COM driver.

        The per-device deadline never resets on missing/flapping metadata. No
        open, mode request, protocol or driver installation occurs in this gate.
        """
        self.state['phase'] = 'WAIT_INITIAL_INTERFACE'
        require(win.inventory() == [], '请先正常关机并拔下 USB，再重新打开本程序。')
        print('等待接口已就绪：现在插入已关机的 P011，不按其他键。', flush=True)
        deadline = time.monotonic() + wait_seconds
        seen_id = None
        readiness_deadline = None
        last_snapshot = object()
        notified = False
        while True:
            require(time.monotonic() < deadline, '等待连接超时。')
            if readiness_deadline is not None and time.monotonic() >= readiness_deadline:
                info = self.state.get('initial_last_node', {})
                raise RuntimeError('下载接口持续未就绪：started=%s，problem=%s，COM=%s；'
                    '本轮未打开串口或发送 MODE，请保留日志核对绑定状态。' %
                    (info.get('started', 'unknown'), info.get('problem', 'unknown'), info.get('port') or '(无)'))
            try:
                rows = win.inventory()
            except win.TransportRefusal as exc:
                if str(exc) != 'PnP status unavailable (CONFIGRET 13)':
                    raise
                rows = None
                if readiness_deadline is None:
                    readiness_deadline = time.monotonic() + readiness_seconds
            snapshot = None if rows is None else [dict(pid=r.get('pid'), port=r.get('port'),
                devinst=r.get('devinst'), started=r.get('started'), problem=r.get('problem'),
                id_sha256=hashlib.sha256(r.get('id', '').encode()).hexdigest()) for r in rows]
            if snapshot != last_snapshot:
                self.event('INITIAL_PNP_SNAPSHOT', nodes=snapshot)
                self.events.flush()
                last_snapshot = snapshot
            if rows:
                if any(row.get('pid') == '4064' for row in rows):
                    raise RuntimeError('设备已进入正常系统，未捕获下载接口；请关机拔线后重新运行。')
                require(len(rows) == 1 and rows[0].get('pid') == '4D00', '首次连接发现多个或未知接口，已停止。')
                row = rows[0]
                require(isinstance(row.get('id'), str) and row['id'], '首次节点缺少 USB 身份，已停止。')
                if seen_id is None:
                    seen_id = row['id']
                require(row['id'] == seen_id, '等待首次接口就绪时 USB 身份变化，已停止。')
                self.state['initial_last_node'] = snapshot[0]
                if readiness_deadline is None:
                    readiness_deadline = time.monotonic() + readiness_seconds
                if row.get('started') is True and row.get('problem') == 0 and row.get('port'):
                    win._identity(row)
                    self.event('INITIAL_INTERFACE_READY', node=snapshot[0])
                    self.events.flush()
                    # The boot interface is brief: open immediately once fully
                    # ready, without adding the post-MODE stability delay here.
                    return row
                if not notified:
                    print('下载接口已出现，正在等待 Windows 完成串口启动；无需重复安装驱动。', flush=True)
                    notified = True
            time.sleep(.02)

    def connect(self, wait_seconds=300):
        self.open(self.wait_initial_ready(wait_seconds))
        self.state['target_id_hash'] = hashlib.sha256(self.node['id'].encode()).hexdigest()
        self.state['port'] = self.node['port']
        # One active MODE followed by deliberate fresh handle. No failed TX retry.
        self.state['phase'] = 'SEND_MODE'
        self.send_once(MODE, 'MODE', True)
        self.close_handle()
        new_node = self.wait_mode_reenumeration()
        self.open(new_node)
        # MODE may echo on some driver versions. Preserve and allow only exact echo.
        pending = self.serial.read_available()
        if pending:
            self.rx.write(pending)
            require(pending == MODE, '模式切换后收到未知主动数据。')
        self.state['phase'] = 'SYNC_CRC'
        version = self.exchange(b'\x7e', 'SYNC_CRC', codec.CRC16, True, 0x81, 12)
        require(version == codec.AUTOD_PAYLOAD, '不是支持的 AutoD 版本。')
        controls = [('CONNECT_CRC16', 0x80, 0), ('EXEC_BUILTIN_CRC16', 0x80, 0),
                    ('SYNC_SUM16_VERSION', 0x81, 12), ('CONNECT_SUM16', 0x80, 0),
                    ('KEEP_CHARGE_SUM16', 0x80, 0), ('EXEC_BUILTIN_SUM16', 0x96, 256),
                    ('DISABLE_TRANSCODE_SUM16', 0x80, 0)]
        for operation, code, size in controls:
            self.state['phase'] = operation
            mode = codec.CRC16 if operation.endswith('CRC16') else codec.SUM16
            payload = self.exchange(codec.build_fixed(operation), operation, mode, True, code, size)
            if code == 0x81:
                require(payload == codec.AUTOD_PAYLOAD, 'SUM16 AutoD 版本不匹配。')
            if code == 0x96:
                require(payload == codec.OBSERVED_CAPABILITY_PAYLOAD, '不支持的下载能力结构。')
        self.state['fdl2_ready'] = True
        self.state['phase'] = 'STORAGE_READY'
        print('已进入内置下载模式，开始核对分区。', flush=True)

    def read_partition(self, name, path):
        require(name in SIZES, '不支持的读取目标。')
        require(self.state.get('fdl2_ready'), '下载阶段未确认。')
        self.exchange(select(0x10, name), 'READ_START:' + name)
        digest = hashlib.sha256()
        last_progress = -1
        with pathlib.Path(path).open('xb') as target_file:
            for offset in range(0, SIZES[name], STEP):
                raw = self.exchange(packet(0x11, struct.pack('<II', STEP, offset)),
                    'READ:' + name + ':' + str(offset), expected_type=0x93, expected_size=STEP)
                target_file.write(raw)
                digest.update(raw)
                progress = (offset + STEP) * 100 // SIZES[name]
                if SIZES[name] >= 10485760 and progress // 5 != last_progress:
                    last_progress = progress // 5
                    print('读取 %s：%d%%' % (name, progress), flush=True)
            target_file.flush()
            import os
            os.fsync(target_file.fileno())
        self.exchange(packet(0x12), 'READ_END:' + name)
        return digest.hexdigest()

    def write_system(self, path, expected_sha, allowed_sha):
        require(expected_sha in allowed_sha and pathlib.Path(path).stat().st_size == SIZES['system'] and
                sha_file(path) == expected_sha, '完整 system 镜像校验失败。')
        require(self.state.get('fdl2_ready') and not self.state['write_started'], '写入状态不允许。')
        self.state['write_started'] = True
        self.exchange(select(1, 'system'), 'WRITE_START:system')
        digest = hashlib.sha256()
        with pathlib.Path(path).open('rb') as source:
            for offset in range(0, SIZES['system'], STEP):
                raw = source.read(STEP)
                require(len(raw) == STEP, '完整镜像中途变短，停止且不发送 END。')
                digest.update(raw)
                self.exchange(packet(2, raw), 'WRITE:system:' + str(offset))
                self.state['write_bytes_acked'] += STEP
                if (offset + STEP) % (16 * 1048576) == 0:
                    print('写入 system：%.1f%%' % ((offset + STEP) * 100 / SIZES['system']), flush=True)
            require(source.read(1) == b'' and digest.hexdigest() == expected_sha, '发送内容身份变化，停止。')
        self.exchange(packet(3), 'WRITE_END:system')
        self.state['write_end_ack'] = True

    def close(self):
        try:
            self.close_handle()
        finally:
            for stream in (self.tx, self.rx, self.events):
                stream.close()
