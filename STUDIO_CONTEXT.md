
---

## 17. 界面 UI 优化 + 自定义背景

- 界面整体改为卡片式布局：窗口背景可自定义，内容区为居中卡片，四周边距露出背景。
- 新增 `界面设置` 标签页，功能包括：
  - 背景图片：支持 png / jpg / jpeg / gif / bmp / webp（依赖 Pillow）。
  - 背景颜色：取色器选择，作为无图片或留边时的底色。
  - 适应方式：填充窗口（裁剪）、适应窗口（留边）、平铺、居中。
  - 主题：浅色 / 深色，使用 ttk clam 主题自定义配色。
  - 背景预览：小画布实时预览当前背景效果。
  - 应用背景 / 清除背景 / 恢复默认外观。
- 菜单栏新增 `界面` 菜单，可快捷选择背景图片、背景颜色、切换浅色/深色主题。
- 顶部新增标题栏，状态栏新增进度条（构建时显示并滚动）。
- 界面设置会自动保存到仓库根目录 `studio_settings.json`，项目文件 `.rms.json` 也会保存这些字段。
- 注意：背景图片本身不会嵌入项目文件，只保存图片路径；换机器需要重新选择图片。

## 18. 试听预览（音频预览）

- 新增 `studio/preview_audio.py`：用 `mido` 读取 MIDI，按 RedPiano 家族映射（pno / lead / pad / bass / drum）用 numpy 合成波形，再写入 WAV。
- 依赖：`mido`、`numpy`、`soundfile`；播放优先 `winsound`，失败时回退 `ffplay`。
- GUI 音效包页新增 `试听预览` 区域：预览秒数（0=完整）、生成试听预览、播放/停止、打开预览文件。`工具` 菜单也有 `试听预览`。
- 生成文件放在 `output\试听预览_<MIDI名>.wav`。
- 已生成交付文件：`output\试听预览_葡萄成熟时_完整.mp3`（320 kbps，约 10.8 MB），源 MIDI 为 `1_陈奕迅 - 葡萄成熟时_(Instrumental)_NNTranscription.mid`。注意原始人声/完整 MIDI 已不在工作目录，只有伴奏版。

### 18.1 真实采样预览

- `studio/preview_audio.py` 现在优先读取 `minecraft-redstone-music/assets/qzpno_mv.zip` 里的真实 `.ogg` 采样，并按 RedPiano 映射（band + 力度层 + 音高偏移）渲染，输出更接近游戏内音符盒实际效果。
- 找不到采样包时自动回退到原来的合成音色。
- 已生成两版交付文件：
  - `output\试听预览_葡萄成熟时_完整_采样版.mp3`（真实资源包采样，推荐）
  - `output\试听预览_葡萄成熟时_完整_合成版.mp3`（旧合成版，保留备用）

### 18.2 工作室内置试听预览修复与入口

- `歌曲与检查` 标签页也新增了 `试听预览` 按钮，和 `工具` 菜单、`音效包` 页里的入口一致。
- 修复了预览线程直接调用 Tkinter `after` 的线程安全问题：后台线程完成后把结果放入 `queue.Queue`，主线程用 `after` 轮询并调用完成回调，预览生成后能可靠自动播放。
- 默认走 `qzpno_mv.zip` 真实采样；无采样包时自动回退合成音色。

### 18.3 音效包标签页滚动

- 用户反馈：`音效包` 页内容较长，窗口小的时候下面的 `试听预览` 区域看不到。
- 已把 `音效包` 页改为 Canvas + 垂直 Scrollbar 的滚动容器，内部所有控件放在可滚动的 `inner` 框架中。
- 鼠标滚轮已递归绑定到内部控件；窗口放大后无需滚动，窗口缩小时可滚动到 `试听预览`。

### 18.4 预览跟随乐器映射

- 用户反馈：如果使用乐器映射，试听预览也应该用同一套映射。
- 采样预览原先固定使用 skill 自带 qzpno 映射，忽略 `吉他 -> 原版吉他`、`弦乐 -> 长笛`、`Voice -> 钢琴` 选项。
- 已改：`studio\preview_audio.py` 的 `render_notes_sampled` 新增 `guitar` / `pad_flute` 参数；命中 lead（吉他）或 pad（长笛）时改用对应合成音色，其余声部仍用 qzpno 真实采样；`render_midi_to_wav` 会把这两个参数传进去。
- `voice_to_piano` 原本已通过 `parse_midi` 生效，继续保留。
- 这样工作室里勾选 `吉他 -> 原版吉他`、`弦乐/铺底 -> 长笛`、`Voice -> 钢琴` 或选择 `NeuralNote 乐器映射` 预设时，试听预览会跟随同样的映射。

## 19. MuseScore MS Basic 音效包

- 新增 `studio/musescore_pack.py`：用 MuseScore Studio 4 的 MS Basic 音色离线渲染 RedPiano 所需的 103 个采样，生成可替换 qzpno_mv.zip 的资源包。
- 依赖：MuseScore 4 安装在 `C:\Program Files\MuseScore 4\bin\MuseScore4.exe`，音色库 `C:\Program Files\MuseScore 4\sound\MS Basic.sf3`；Python 侧依赖 `mido`、`numpy`、`soundfile`。
- 映射：pno -> Acoustic Grand Piano (GM 0)，lead -> Distortion Guitar (GM 29)，pad -> String Ensemble 1 (GM 48)，bass -> Electric Bass pick (GM 33)，drum -> 标准鼓组（kick 36 / snare 38 / hihat 42 / tom 45 / crash 49）。
- 每个采样用 MuseScore 按固定时间槽渲染，再按槽位切片、去静音、按原始 qzpno 采样峰值归一化，最后编码为 OGG/Vorbis。
- 输出：`output/musescore_instrument_pack.zip`，内部仍使用 `qzpno` 命名空间和相同文件名，可直接替换资源包，无需重新生成机器。
- GUI `音效包` 页新增 `生成 MuseScore 音效包` 按钮；生成完成后自动切换为自定义资源包，并设置 `MuseScore 乐器映射` 预设。
- 命令行：`python -m studio.musescore_pack --out output/musescore_instrument_pack.zip`。
- 注意：MuseScore 4 的 CLI 会输出 `failed open log file` 警告，但 WAV 能正常生成；生成过程中不要关闭 MuseScore 弹窗（如果有）。

### 18.5 预览使用自定义音效包

- `studio/preview_audio.py` 的 `render_notes_sampled` / `render_midi_to_wav` 新增 `sample_zip` 参数；工作室在 `音效包` 页选择 `使用自定义 qzpno_mv.zip` 时，试听预览会直接读取该自定义资源包（例如 `output/musescore_instrument_pack.zip`）的采样，而不是 skill 自带包。
- 未启用自定义包时仍回退到 `qzpno_mv.zip`。

## 20. FL Studio 默认乐器音效包

- 新增 `studio/flstudio_pack.py`：从本机 FL Studio 2026 安装目录读取默认乐器采样，离线生成 RedPiano 所需的 103 个采样。
- 采样来源：
  - pno: `Data\Patches\Packs\Instruments\Keyboard\Close Grand\Close Grand 1..88.wav`（88 键半音，A0..C8）
  - lead: `Data\Patches\Packs\Instruments\Guitar\Jazz\Jazz Guitar (1..12).wav`
  - bass: `Data\Patches\Packs\Instruments\Bass\Acoustic\Acoustic Bass (1..10).wav`
  - pad: `Data\Patches\Packs\Instruments\Orchestral\Strings Section\OSTR C1..C6/F1..F5.wav`
  - drum: `Data\Patches\Packs\Drums\Kicks\909 Kick.wav`、`Snares\909 Snare.wav`、`Hats\909 CH 1.wav`、`Toms\909 Tom.wav`、`Cymbals\909 Crash.wav`
- FL Studio 的 `.wav` 实际是 RIFF 容器包裹 Ogg Vorbis（`fmt ` tag 0x674F），`soundfile` 不能直接读。`studio/flstudio_pack.py` 用 `_extract_ogg` 解析 RIFF 取出 `data` 再解码。
- 音高识别：纯 numpy YIN（`yin_f0`，11025 Hz，2048 帧）自动测出各乐器采样根音；Close Grand 已确认按半音从 A0(21) 到 C8(108) 排列。
- 变调：`pitch_shift` 用 `scipy.signal.resample_poly` 按 `Fraction(2**(semitones/12)).limit_denominator(1000)` 重采样，再裁剪/补齐到 2.8 s（鼓 0.6 s 等）。
- 输出：`output/flstudio_instrument_pack.zip`，内部仍是 `qzpno` 命名空间、相同 103 个文件名，可直接替换资源包。
- GUI `音效包` 页新增 `生成 FL Studio 音效包` 按钮和 `FL Studio 乐器映射` 预设；生成后自动切换为自定义资源包。
- 命令行：`python -m studio.flstudio_pack --out output/flstudio_instrument_pack.zip`。
- 注意：需要本机安装 FL Studio 2026（或 FL Studio 20），默认路径 `C:\Program Files (x86)\Image-Line\FL Studio 2026`；采样许可归 Image-Line，仅本地试听/替换用，不要随作品分发。

## 21. 在线音色库（SoundFont 搜索、预览、生成资源包）
- 新增 studio/sf2_synth.py：纯 Python 的 SF2 解析器 + 采样合成器。
  - 支持解析 RIFF sfbk 的 phdr/pbag/pgen/inst/ibag/igen/shdr/smpl。
  - 修正 SF2 生成器枚举：GEN_SAMPLE_ID=53、GEN_SAMPLE_MODES=54、GEN_OVERRIDING_ROOT_KEY=58、GEN_COARSE_TUNE=51、GEN_FINE_TUNE=52、GEN_SCALE_TUNING=56、循环粗偏移 45/50、包络 33-38。
  - 关键：必须使用 phdr/inst 中的 bag_index 跳转，不能按数组下标枚举。
  - SoundFont.render_note(preset_index, note, velocity=100, duration=2.0, sr=SR) 输出单音 PCM（峰值归一化）。
- 新增 studio/online_soundpack.py：
  - search_catalog / search_online（musical-artifacts.com artifacts.json，使用 mirrors 中的直接 .sf2/.sf3 链接，url 作为页面地址）。
  - download(url, dest, progress)、list_local_soundfonts()、list_presets(sf2_path)、preview(...)。
  - build_pack(sf2_path, mapping, out_zip, log)：按 pno/lead/pad/bass/drum 映射 preset，渲染 103 个样本并生成 qzpno 资源包。
  - CLI：python -m studio.online_soundpack --sf2 file.sf2 --out pack.zip --pno 0:0 --lead 0:29 --pad 0:48 --bass 0:33 --drum 128:0，支持 --list。
- GUI：studio/app.py 新增【在线音色库】标签页。
  - 在线搜索（musical-artifacts.com）、结果列表、下载所选 / 打开页面。
  - 本地 SoundFont 选择（刷新 / 浏览 / 加载 preset）、5 个家族映射下拉框。
  - 试听单音 / 试听音阶 / 停止、生成资源包、日志。
  - 生成完成后自动切换 Sound 页为自定义资源包，预设显示【在线音色库（自定义）】。
- 已验证：TimGM6mb.sf2 解析 136 presets；pno=126、lead=97、pad=134、bass=93、drum=4 映射正确；build_pack 无静音警告，输出 103 样本。

## 22. 工作目录优化记录（本次）
- 删除旧构建/部署目录：build/ (72.5 MB)、dist2131/ (36.3 MB)、dist23232/ (空)、outao/ (36.3 MB)、putao/ (36.3 MB)。
- 保留最新机器包 dist/ (56.7 MB, 2026/10/10 17:53)。
- 删除根目录 _test_hello.txt；清理所有 __pycache__/。
- 将 output/试听预览_陈奕迅 - 葡萄成熟时new.wav (22.9 MB) 转码为 MP3 (6.2 MB) 并删除 WAV。
- .gitignore 增加 dist/、output/、studio_settings.json；执行 git gc --prune=now。
- 工作目录总大小从 340.1 MB 降至约 141.4 MB，共节省约 198.7 MB。
