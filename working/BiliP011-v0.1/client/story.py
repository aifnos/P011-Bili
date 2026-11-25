"""Official Story cursor/history; never substitutes recommendation/search feeds."""
import threading
class StoryFeed:
    def __init__(self, fetch,fetch_with_cancel=None):
        self.fetch=fetch;self.rows=[];self.seen=set();self.page=1;self.offset='';self.index=-1;self.base=0
        self.lock=threading.RLock();self.fetch_with_cancel=fetch_with_cancel
    def extend(self,cancel=None):
        for _ in range(3):
            if cancel and cancel.is_set():raise ValueError('story canceled')
            args={'page':self.page,'offset':self.offset}
            data=self.fetch_with_cancel(args,cancel) if self.fetch_with_cancel else self.fetch(args)
            if cancel and cancel.is_set():raise ValueError('story canceled')
            if not isinstance(data,dict) or data.get('source')!='official-story' or not isinstance(data.get('items'),list):raise ValueError('story schema')
            self.page+=1;offset=data.get('offset','')
            if not isinstance(offset,str) or len(offset)>20 or (offset and not offset.isdigit()):raise ValueError('story cursor')
            self.offset=offset;count=0
            for row in data['items'][:20]:
                if not isinstance(row,dict):continue
                key=(row.get('bvid',''),row.get('cid',''))
                if not all(isinstance(x,str) for x in key) or not key[0] or not key[1] or key in self.seen:continue
                self.rows.append(dict(row));self.seen.add(key);count+=1
            if count:return
            if not data.get('more'):break
        raise ValueError('story empty')
    def target(self, delta):
        with self.lock:
            target=self.index+delta
            if target<0:raise IndexError('first item')
            if target>=len(self.rows):self.extend()
            return target,dict(self.rows[target])
    def ahead(self,expected,cancel):
        return self.lookahead(expected,cancel,1)[0]
    def lookahead(self,expected,cancel,count=2):
        with self.lock:
            if self.index!=expected or cancel.is_set():raise ValueError('story moved')
            if self.index+1>=len(self.rows):self.extend(cancel)
            # Do not fetch another page while a ready next item can be used.
            # The next committed swipe will top up this two-item horizon.
            return [dict(row) for row in self.rows[self.index+1:self.index+1+min(2,count)]]
    def commit(self,index):
        with self.lock:
            self.index=index
            if self.index>32:
                remove=self.index-24;self.rows=self.rows[remove:];self.index-=remove;self.base+=remove
            if len(self.seen)>512:self.seen={(x['bvid'],x['cid']) for x in self.rows}
