<div align="center">

# McMusicMaker · 红石音乐机

把 MIDI 变成 Minecraft 里真正会演奏的音符盒红石机器。

[![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/License-PolyForm%20Noncommercial%201.0.0-orange.svg?style=flat-square)](LICENSE)
[![Minecraft: Java 1.21–1.21.10](https://img.shields.io/badge/Minecraft-Java%201.21%E2%80%931.21.10-62B47A.svg?style=flat-square)](minecraft-redstone-music/docs/VERSION_TACTICS.md)
[![Windows](https://img.shields.io/badge/交付-Windows-4B8BF5.svg?style=flat-square)](#环境要求)

<a href="docs/assets/skill_video.mp4"><img src="docs/assets/hero.gif" width="640" alt="McMusicMaker 演示"></a>

**▶ [播放完整演示视频（57 秒 · 五种机型、走线设计器、命令方块编辑器）](docs/assets/skill_video.mp4)**

</div>

---

## 它能做什么

- 输入一首 MIDI（也可以先给 MP3），分析歌曲并选择适合的红石机器
- 把声部安排成钢琴、贝斯、主音、铺底和鼓
- 生成数据包、资源包和所需模组，输出可双击安装的 `DEPLOY_TO_GAME.bat`
- 最终由 Minecraft 世界里的**真实音符盒和红石线路**演奏，而不是播放原曲音频

## 两种使用方式

### 1. 红石音乐工作室（推荐）

双击 `启动红石音乐工作室.bat`，或运行：

```powershell
python redstone_music_studio.py
```

功能：歌曲检查、机器生成（`inplace` / `swave` / `multilane` / `tube`）、3D 预览、音效包（NeuralNote / MuseScore / FL Studio / 在线 SoundFont）、试听预览、一键安装、项目保存。详细说明见 [studio/README.md](studio/README.md)。

### 2. 交给 AI agent

用 Codex、Claude Code 或其他可读写文件的 agent 打开整个仓库，发送：

```text
请使用仓库里的 minecraft-redstone-music skill，帮我把一首歌做成 Minecraft 红石音乐机。
我的 Minecraft 是 Java 版，版本是【填写版本】。
歌曲文件在【填写路径】。
存档在【填写路径；不知道就先帮我找】。
```

详细工作流见 [minecraft-redstone-music/SKILL.md](minecraft-redstone-music/SKILL.md)。

## 机型选择

| 机型 | 特点 | 适合 |
|---|---|---|
| `inplace` 原地紧凑型 | 占地最小，音符集中 | 长歌、小场地、稳定听歌 |
| `swave` S 形折线型 | 线路折返成 S 形，脉冲沿线可见 | 兼顾观赏与占地 |
| `straight` 直线型 | 沿直线铺开，结构最直观 | 短歌、教学、超长空地 |
| `custom` 自定义路线 | 浏览器设计器自绘路线 | 绕建筑或景观 |
| `multilane` 多轨并行型 | 声部分轨并行，同刻音符横向对齐 | 大型舞台效果 |
| `tube` 圆环音轨型 | 圆环音轨 + 中心直线通道 | 工作室生成的环绕型舞台 |

## 游戏内必敲指令

`<ns>` 为构建时的命名空间：

```mcfunction
/reload
/tick rate 80
/function <ns>:setup
```

控制台按钮：`play` / `stop` / `view` / `preload` / `cfg/polytoggle` / `cfg/humantoggle` / `stand` / `cam`。

听完后 `/tick rate 20` 还原。

## 安装

构建完成后，双击 `dist\DEPLOY_TO_GAME.bat`，重启游戏，按 agent/工作室提示启用资源包并输入命令。安装回执见 `dist\DEPLOY_RECEIPT.txt`。

## 环境要求

- Windows
- Minecraft Java Edition 1.21–1.21.10
- 存档开启作弊，或拥有 OP 权限
- 安装模组后需重启一次游戏

## 更多文档

- [Skill 完整工作流程](minecraft-redstone-music/SKILL.md)
- [游戏内操作与排错](minecraft-redstone-music/QUICKSTART.md)
- [模组与资源包说明](minecraft-redstone-music/BINARIES.md)
- [版本适配策略](minecraft-redstone-music/docs/VERSION_TACTICS.md)
- [工作室详细说明](studio/README.md)
- [开发记录](STUDIO_CONTEXT.md)

## 许可

代码以 [PolyForm Noncommercial 1.0.0](LICENSE) 发布，仅限非商业使用；商用授权请联系作者。

随包钢琴采样 Salamander Grand Piano v3 (CC BY 3.0)，署名见资源包内 `CREDITS.txt`。

<div align="center">
<sub>把你想听的歌交给工作室或 agent，剩下的交给它。</sub>
</div>
