# 星穹铁道探索与常驻活动 Skills

供 Codex 使用的两个技能包，复用三月七小助手的观察、输入、路线和战斗能力，按游戏内实际进度核验结果。

| 技能 | 用途 |
| --- | --- |
| [treasure-opening](treasure-opening/) | 指定区域宝箱与特殊寻宝目标：地图定位、路线移动、交互与收集核验 |
| [star-rail-permanent-events](star-rail-permanent-events/) | 常驻活动、常时传略与往期活动：入口定位、剧情与玩法推进、领奖及完成核验。纯日常清体力使用三月七小助手技能。 |

## 安装

克隆或下载本仓库，将 `treasure-opening/` 和 `star-rail-permanent-events/` 文件夹复制到 Codex 的技能目录 `~/.codex/skills/`。确保 `SKILL.md` 位于同名文件夹内，避免重复嵌套目录，并保留 `references/`、`scripts/` 等配套文件。

也可单独下载整包：[宝箱技能 ZIP](treasure-opening.zip)、[活动技能 ZIP](star-rail-permanent-events.zip)，解压后按同样方式安装。

两个技能相互引用控制参考与探索能力，请一起安装。

## 运行依赖

- 需要安装并配置最新版 `march7th-assistant` 技能，以及可运行的 Windows 游戏环境和适配的三月七小助手源码环境。[三月七小助手上游仓库](https://github.com/moesnow/March7thAssistant)。该技能需包含 `references/star-rail-wiki.md`、`references/star-rail-wiki-index.md` 和 `scripts/search_wiki.py` 等 Wiki 查询配套文件。本仓库不包含该依赖技能或完整游戏自动化运行环境。
- 使用源码环境已有的 Python 和依赖。技能引用的地图定位、路线、OCR 及控制能力以实际源码版本为准；源码中的新能力不保证上游已发布安装版已有。
- 活动技能的控制脚本依赖三月七小助手仓库及其运行环境，不是可独立执行的程序。具体启动方式见 [常驻会话说明](star-rail-permanent-events/references/session-control.md)。
- 新版小助手支持用户在「设置 → 杂项」开启「免 UAC 运行」。`m7a.exe --status` 返回 `elevation: task` 时，官方任务和流程无需重复确认；`uac` 才需要用户确认。该功能只对对应安装生效，不自动覆盖直接运行的 Python 活动控制器；控制器优先复用已有会话。
- 活动控制会话的点击、拖动和 OCR 区域使用返回画面的 **1920×1080 归一化坐标**；更换画面布局或地图标定后需重新确认位置。

2026-11-07 已在小助手 v2026.11.7 和真实游戏环境验证：`uac_free: on`、`elevation: task`，运行 `m7a.exe game --after-finish None` 免弹窗成功，退出码为 0。

## 用法示例

安装后在 Codex 中说明目标与范围，例如：

```text
使用 treasure-opening，收集我当前区域剩余的普通宝箱，以地图计数核验。

使用 star-rail-permanent-events，继续当前常时传略活动，完成主流程和常驻奖励领取。

使用 star-rail-permanent-events，只完成这个活动的剧情，保留可观看的剧情，不扩展到全收集。
```

开始前保持游戏可捕获，并避免多个程序同时控制游戏。中断后先确认当前任务和游戏状态再续跑；最终以游戏内目标、计数和奖励状态判断完成。
