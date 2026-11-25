"""Make a local static index of already verified public device captures.

Does not modify screenshot pixels, source logs, or an existing result ZIP.
"""
import argparse,hashlib,html,json,pathlib
from client_results import CAPTURES

LABELS={'toolbox-home':'工具箱首页','toolbox-files':'文件中心','toolbox-text':'TXT 阅读','toolbox-image':'图片预览',
 'toolbox-snake':'贪吃蛇：两侧大按键','toolbox-2048':'2048','toolbox-bricks':'打砖块','toolbox-dashboard':'系统仪表盘','toolbox-curves':'采样曲线','toolbox-processes':'只读进程',
 '01-recommendations':'视频推荐','02-next-cards':'推荐翻页','03-video-details':'视频详情 / 分 P','04-offline-keyboard':'离线拼音输入','05-search-input':'中文搜索输入','06-search-results':'搜索结果',
 '07-bangumi':'番剧目录','08-input-error':'输入错误 / 重试入口','09-description':'完整简介','10-qualities':'授权画质 / 编码','11-comments':'热门评论','12-comments-next':'评论翻页','13-bangumi-details':'番剧选集','14-comment-replies':'评论回复','15-bangumi-scrolled':'选集滑动后',
 'player-landscape':'横屏视频 / 控件隐藏','player-paused':'暂停与进度条','player-quality':'播放中切画质','player-danmaku':'弹幕绘制','player-portrait':'整屏竖屏','player-portrait-controls':'竖屏大按钮','player-next':'竖屏滑切下一视频',
 'player-codecs':'播放中选择编码','player-hevc':'实际 HEVC 解码','player-av1':'实际 AV1 解码',
 'player-types':'合成弹幕类型样例 / 无矩形底','player-types-later':'暂停后的第二帧 / 稳定性对照','player-dm-settings':'弹幕分类型开关',
 'player-story':'官方 Story 短视频流','player-story-next':'跨批次上滑后的官方 Story',
 '16-input-component':'原厂键盘复用 / 输入适配器','17-api-high-qualities':'接口实际高画质 / 滚动到末项','player-dm-layout':'弹幕区域 / 不透明度 / 字号 / 速度',
 'player-dm-half':'50% 区域与 75% 不透明度','player-aspect':'画面比例选项','player-fill':'填满裁切','player-stats':'实时播放信息',
 'player-story-drag':'短视频跟手拖动 / 回弹前','player-seek-preview':'横滑进度预览 / 松手提交',
 'feature-live-list':'官方直播目录','feature-live-detail':'直播间详情','player-comments':'播放中查看评论','player-listen':'听视频 / 停止视频解码','player-live':'直播播放 / 不提供快进',
 'catalog-popular':'发现 / 热门','catalog-weekly':'发现 / 每周必看','catalog-timeline':'发现 / 番剧时间表','player-subtitles':'真实 CC 字幕','player-chapters':'官方章节列表','player-subtitle-settings':'字幕字号与时间偏移','player-timed-preview':'官方进度缩略图'}

def main():
    p=argparse.ArgumentParser();p.add_argument('directory',type=pathlib.Path);a=p.parse_args();root=a.directory.resolve()
    result=json.loads((root/'result.json').read_text(encoding='utf-8'))
    if not result.get('recovery_passed') or not result.get('ui_automation',{}).get('passed'):raise ValueError('Only completed passing device evidence')
    index=json.loads((root/'capture-index.json').read_text(encoding='utf-8'))
    cards=[]
    for item in index:
        name=item['name']
        if name not in CAPTURES:raise ValueError('Not an allowed public capture')
        path=root/'ui-crops'/(name+'.png')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=item['crop_sha256']:raise ValueError('Capture changed')
        raw_size=item.get('raw_size',[800,480]);raw_label='%d×%d 原始窗体图'%tuple(raw_size)
        cards.append('<figure><a href="ui-crops/'+name+'.png"><img loading="lazy" width="800" height="268" src="ui-crops/'+name+'.png" alt="'+html.escape(LABELS[name])+'"></a><figcaption>'+html.escape(LABELS[name])+' <a href="device/screenshots/'+name+'.png">'+raw_label+'</a></figcaption></figure>')
    qa=result['ui_automation'];counts='Bili %d 项 · 播放器 %d 项 · 工具箱 %d 项 · %d 张图'%(len(qa.get('checks',[])),len(qa.get('player_checks',[])),len(qa.get('toolbox_checks',[])),len(index))
    body='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' file:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>P011 实机页面截图</title><style>body{margin:0;background:#080f17;color:#edf5fa;font:16px system-ui,sans-serif}header{max-width:1624px;margin:28px auto;padding:0 16px}h1{font-size:28px}p{color:#a6c7d1;line-height:1.65}main{max-width:1624px;margin:auto;padding:0 12px 32px;display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,640px),1fr));gap:16px}figure{margin:0;background:#142330;border-radius:12px;overflow:hidden}img{display:block;width:100%;height:auto}figcaption{padding:12px;font-size:18px}a{color:#66dccf}figcaption a{float:right;font-size:14px}</style><header><h1>P011 · 实机页面截图</h1><p>'''+html.escape(counts)+'''</p><p>全部来自笔端实际运行，不是设计稿。按实际窗体提取800×268内容区：原生长条窗口不裁切，旧窗体只去掉上下空白，原图始终保持不变。竖屏图按设备物理屏幕保存，未为展示偷偷旋转。自动播放器静音，声音与玻璃触摸仍需人工确认；原厂文件、进程与 60 秒息屏设置已独立恢复核验。</p></header><main>'''+''.join(cards)+'</main></html>'
    target=root/'SCREENSHOTS.html'
    with target.open('x',encoding='utf-8') as f:f.write(body)
    print('GALLERY='+str(target));print('CAPTURES='+str(len(cards)))

if __name__=='__main__':main()
