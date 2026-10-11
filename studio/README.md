# 红石音乐工作室 v0.3.0

这是 minecraft-redstone-music skill 的 Windows 桌面 GUI 封装。

## 启动

双击仓库根目录的：

启动红石音乐工作室.bat

或者命令行：

python redstone_music_studio.py

## 功能

- 歌曲与检查：选择 MIDI，调用 midi_report.py 查看时长、乐器、丢音和占地。
- 机器与生成：设置命名空间、MC 版本、机器形态、原点坐标、存档路径、依赖 jar，调用 prepare_all.py 生成安装包。
- 音效包：吉他换原版吉他、弦乐换长笛、Voice 换钢琴、鼓组 crash 音量。
- 3D 预览 / 轨道布局：多轨机器可用等距 3D 视图预览，拖动轨道改 Z / Y，Shift+拖动改 X，保存为 params.json。
- 自研布局设计器：不依赖 skill 自带 HTML 设计器，内置自定义路线编辑器，可点击加路线点、拖动、右键删除、生成方形/圆形/螺旋，并保存 params.json。
- 一键安装：确认本机原生运行且 Minecraft 已退出后，可直接运行 DEPLOY_TO_GAME.bat，并自动检查回执。
- 部署页：检查 DEPLOY_RECEIPT.txt，打开 dist 或世界目录。

## 重要提醒

- 如果软件运行在沙箱或远程环境，请使用打开 dist 文件夹后自己双击安装器，不要用一键安装。
- 一键安装只适合你本机原生运行、且清楚风险的情况。
- 底层仍使用原 skill 的 Python 脚本，软件只做界面、参数收集和日志显示。

## 圆环音轨 + 中心直线通道

在机器与生成页点生成圆环音轨参数：

- 输入圆环半径和轨道数量
- 软件会生成 tube_params.json
- 使用 multilane 形态生成机器
- 轨道从截面看围绕中心通道形成圆环，但每条轨道仍是直轨
- 推荐原点 Y 设为 225 左右

## 延音填补空档

在音效包页可启用延音填补空档：

- 最大空档秒数：把休止处也延长，最多延长多少秒
- 旋律延音上限秒数：传给 build 的 --melcap
- 适合 pad / lead / bass；piano 是单次衰减样本，不能无限延音

## 各乐器独立音量

音效包页支持分别调节：

- 钢琴 pno
- 主音/吉他 lead
- 弦乐/铺底 pad
- 贝斯 bass
- 鼓组 drum
- 锣声 crash

范围 0-200%，生成自定义资源包时会写入对应音量。

## NeuralNote 乐器映射

音效包页提供 NeuralNote 乐器映射预设：

- 钢琴 -> 钢琴
- 吉他/主音 -> 原版吉他
- 弦乐/人声 -> 长笛/钢琴
- 贝斯 -> 贝斯
- 鼓 -> 鼓组

也可以直接点生成 NeuralNote 音效包，输出 neuralnote_instrument_pack.zip。

## 界面设置 / 自定义背景

界面新增 `界面设置` 标签页：

- 背景图片：png / jpg / jpeg / gif / bmp / webp
- 背景颜色
- 适应方式：填充窗口（裁剪）/ 适应窗口（留边）/ 平铺 / 居中
- 主题：浅色 / 深色
- 背景预览

菜单栏 `界面` 菜单可以快速选择背景图片、背景颜色和切换主题。界面设置会自动保存到 `studio_settings.json`。

## 试听预览（音频预览）

- `studio/preview_audio.py`：MIDI -> 合成 WAV，按 RedPiano 家族音色映射。
- GUI 音效包页新增 `试听预览` 区域：预览秒数（0=完整）、生成试听预览、播放/停止、打开预览文件。
- 生成文件：`output\试听预览_<MIDI名>.wav`。

### 真实采样预览

- 默认优先使用 `qzpno_mv.zip` 里的 `.ogg` 真实采样，按 RedPiano 映射渲染；找不到时回退合成音色。
- 交付文件：`output\试听预览_葡萄成熟时_完整_采样版.mp3`（推荐）和 `output\试听预览_葡萄成熟时_完整_合成版.mp3`（备用）。

### 工作室内置试听预览

- `歌曲与检查`、`音效包` 页都有 `试听预览` 按钮，`工具` 菜单也有入口。
- 后台渲染完成后通过队列回到主线程播放，避免 Tkinter 跨线程问题。
- 预览默认使用 `qzpno_mv.zip` 真实采样。

### 音效包滚动

- `音效包` 页支持垂直滚动，窗口较小时可滚到 `试听预览` 区域。
- 支持鼠标滚轮；窗口最大化时内容通常一屏可见。

### 预览跟随乐器映射

- 试听预览会跟随 `音效包` 页的 `吉他 -> 原版吉他`、`弦乐/铺底 -> 长笛`、`Voice -> 钢琴` 选项。
- 使用 `NeuralNote 乐器映射` 预设时，预览同样会应用该映射。
- 未映射的声部继续使用 qzpno 真实采样。

## MuseScore 音效包

- `studio/musescore_pack.py`：用 MuseScore Studio 4 的 MS Basic 音色渲染 RedPiano 采样包，输出 `output/musescore_instrument_pack.zip`。
- GUI `音效包` 页新增 `生成 MuseScore 音效包` 按钮；生成后自动切换到自定义资源包。
- 命令行：`python -m studio.musescore_pack --out output/musescore_instrument_pack.zip`。
- 需要安装 MuseScore 4，默认路径 `C:\Program Files\MuseScore 4\bin\MuseScore4.exe`。

### 预览跟随自定义音效包

- 选择 `使用自定义 qzpno_mv.zip` 后，试听预览会使用该 zip 里的采样；例如选择 `output/musescore_instrument_pack.zip` 即可试听 MuseScore 音色。

## FL Studio 默认乐器音效包

- `studio/flstudio_pack.py`：从本机 FL Studio 2026 安装目录的默认乐器采样生成 RedPiano 采样包，输出 `output/flstudio_instrument_pack.zip`。
- GUI `音效包` 页新增 `生成 FL Studio 音效包` 按钮和 `FL Studio 乐器映射` 预设；生成后自动切换到自定义资源包。
- 命令行：`python -m studio.flstudio_pack --out output/flstudio_instrument_pack.zip`。
- 需要本机安装 FL Studio 2026 或 FL Studio 20。
- 采样许可归 Image-Line，仅本地试听/替换用，不要随作品分发。

## 在线音色库（SoundFont）

- 在【在线音色库】标签页搜索 musical-artifacts.com 的 SoundFont。
- 选择结果后可下载 .sf2/.sf3，或打开页面手动下载。
- 用【本地 SoundFont】下拉框选择已下载/本机文件，点击【加载 Preset】。
- 为钢琴 / 主音 / 铺底 / 贝斯 / 鼓组选择 preset，点击【试听单音/音阶】。
- 点击【生成资源包】，完成后自动切换到自定义资源包；预览会跟随该资源包。
- CLI 等价命令：
  python -m studio.online_soundpack --sf2 file.sf2 --out output/online_instrument_pack.zip --pno 0:0 --lead 0:29 --pad 0:48 --bass 0:33 --drum 128:0
