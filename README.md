# McMusicMaker · MIDI → Minecraft 红石音乐机

把一个 **MIDI 文件** 变成能在 Minecraft Java 版里自动演奏的 **红石音乐机器**。

运行时 = **数据包 + 资源包 `qzpno_mv` + RedPiano 模组 + Fabric API**：数据包经模组驱动真实音符盒，
资源包提供钢琴 / 贝斯 / 主音 / 铺底 / 鼓组采样。`--mc-version` 一个参数即可让数据包、资源包、
模组与安装自动对齐目标版本（支持 **1.21 – 1.21.10**，默认与已验证锚点为 **1.21.8**）。

## 主要功能

- **MIDI → 机器**：解析 MIDI，生成红石机器、数据包、资源包与安装器（`dist/`）。
- **多种形态**：`straight` / `swave` / `inplace` / `multilane`（匀速跑道为当前默认）。
- **红石音乐工作室（GUI）**：Windows 桌面界面，覆盖选曲检查、生成、音效包、3D 预览、在线音色库与部署。
- **自定义音色包**：真实采样、MuseScore 4、FL Studio、在线 SoundFont（.sf2）均可生成资源包并试听。
- **一键部署**：生成 `DEPLOY_TO_GAME.bat`，本机双击即可装进游戏。
- **多版本兼容**：`binaries/` 内置各版本预编译模组 jar。

## 仓库结构

| 目录 | 说明 |
|---|---|
| `minecraft-redstone-music/` | 核心 CLI 与构建脚本（skill），详见其 `README.md` / `QUICKSTART.md` |
| `studio/` | 红石音乐工作室 Windows GUI |
| `mod/redpiano/` | RedPiano Fabric 模组源码（Java 21） |
| `binaries/` | 各 MC 版本预编译模组 jar + 清单 |
| `poc/` | 早期概念验证生成器（历史参考，非生产入口） |
| `docs/` | 演示素材与开发过程记录（历史文档，可能与当前实现不一致） |

## 快速开始

### 图形界面（首次推荐）

双击仓库根目录的 `启动红石音乐工作室.bat`，或命令行：

```powershell
python redstone_music_studio.py
```

### 命令行

```bash
cd minecraft-redstone-music
pip install -r requirements.txt
python scripts/prepare_all.py --midi assets/demo.mid --form swave --ns demo \
    --origin 0 0 255 --mc-version 1.21.8 \
    --world-dir "<存档目录>/saves/<世界>/datapacks" --profile-dir "<.minecraft 目录>"
```

跑完后由**你本人双击** `dist/DEPLOY_TO_GAME.bat` 安装，再按 `QUICKSTART.md` 的清单进游戏。
（脚本依赖仓库结构，务必整仓 clone，不能只拷 `minecraft-redstone-music/` 子目录。）

## 环境要求

- **Windows**（安装器为 `.bat`，目前仅 Windows 交付）
- Python 3.8+，依赖仅 `mido`
- Minecraft Java 版 1.21 – 1.21.10，已装 Fabric Loader + Fabric API
- 需要重新构建模组源码时：JDK 21 + Gradle

## 文档

- [minecraft-redstone-music/README.md](minecraft-redstone-music/README.md)：完整说明与开场提示词
- [minecraft-redstone-music/QUICKSTART.md](minecraft-redstone-music/QUICKSTART.md)：从 `.mid` 到游戏内出声的分步清单
- [studio/README.md](studio/README.md)：GUI 各页功能
- [docs/history/](docs/history/)：开发过程记录（历史）

## 许可

[PolyForm Noncommercial License 1.0.0](LICENSE)，仅限非商业用途。
采样音色版权与署名见资源包内 `CREDITS.txt`。