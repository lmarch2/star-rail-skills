# 常驻活动控制会话

使用小助手源码环境已有的 Python 与依赖；不修改主项目。所有点击、拖动与 OCR 区域使用 **1920×1080** 归一化画面坐标，和客户端返回的 `screen.png` 一致。

## 启动与复用

先定位源码和已有会话。以下变量用实际路径填入；`$eventSession` 优先指向已经运行的会话目录。

```powershell
$eventRoot = '实际的小助手源码目录'
$eventSession = Join-Path $eventRoot '.cache\event-session'
$eventScripts = '实际的本技能目录\scripts'
$eventPython = Join-Path $eventRoot '.venv\Scripts\python.exe'
$eventWorker = Join-Path $eventScripts 'event_session.py'
$eventClient = Join-Path $eventScripts 'session_request.py'
& $eventPython $eventWorker --root $eventRoot --session $eventSession --status
& $eventPython $eventWorker --root $eventRoot --session $eventSession
```

`running` 表示控制进程已就绪，`reused: true` 表示复用现有进程。`starting` 表示正在启动或初始化：用 `--status` 确认变为 `running` 后再提交动作；启动失败查看会话的 `helper.log`。

先区分官方任务与本脚本：新版小助手的 `m7a.exe --status` 返回 `elevation: task` 时，官方任务和流程会复用用户开启的 `March7thAssistantNoUAC`，不再请求 UAC；开关用法见 `march7th-assistant` 技能。该计划任务只启动对应安装的小助手，不是任意 Python 脚本的启动接口。

本脚本直接使用源码环境的 `start_as_admin`，不会因为安装版开启免 UAC 就自动免提权。已有常驻会话应直接复用；确需新建且当前进程未提权时，会使用隐藏窗口请求一次正常提权，出现真实 UAC 才请用户确认。不要另建提权任务或修改现有计划任务来运行本脚本。

多个会话共享同一游戏时，先等当前控制者释放控制权，再接续同一会话；持锁只证明控制器存活，不代表当前轮到自己使用。新版 `--status` 返回 `owner`、`phase`、`active_request` 和 `last_request`，可在控制器忙碌时直接查询，不排队、不激活游戏。`controller` 包含版本、支持动作、启动时间和已加载脚本的 SHA-256；`script_matches:false` 表示磁盘上的控制脚本与运行版本不同。该哈希只覆盖控制脚本，依赖模块修改后仍需重启。已加载所需能力的控制器可直接交接，避免相邻实测之间反复关闭、启动游戏和请求 UAC。磁盘脚本的新动作不会自动进入已运行进程；必须使用新增动作时，在上一轮释放控制后正常停止旧进程并启动新版。

## 提交、观察与接续

将请求保存为 UTF-8 JSON 文件，然后提交一次：

```powershell
& $eventPython $eventClient --session $eventSession --owner "本轮唯一标记" --file '实际请求文件.json' --compact
```

版本 2 首次输入前单独提交 `{"action":"claim"}`，客户端的 `--owner` 为该请求及后续输入提供同一标记。已被其他标记占用时返回 `rejected`，不停止对方剧情或释放对方输入。交接时由当前 owner 单独提交 `{"action":"release"}`：停止剧情、释放按键，返回 `input_released:true` 并清空 owner；下一控制者确认响应完成后再 claim。观察、地图定位与 status 不需要 owner；输入、剧情开关、启动及停止控制器必须匹配 owner。不同会话目录之间仍应只运行一个游戏控制器。

常用请求：

| 目的 | JSON |
|---|---|
| 看画面，不做 OCR | `{"action":"snapshot","ocr":false}` |
| 查看局部文字 | `{"action":"snapshot","ocr_region":[0,0,960,300]}` |
| 只取局部文字，不保存图片 | `{"action":"snapshot","ocr_region":[0,0,960,300],"save_image":false}` |
| 点击已确认按钮 | `{"action":"click","point":[960,900],"wait":0.5}` |
| 按交互键 | `{"action":"key","key":"f","seconds":0.3}` |
| 短距离移动后查看地标 | `{"action":"physical","key":"w","seconds":0.5,"ocr":false}` |
| 相对转镜头后确认视野 | `{"action":"camera","delta":[300,0],"ocr":false}` |
| 开启自动剧情、跳过与战斗检测 | `{"action":"plot","enabled":true,"ocr":false}` |
| 停止自动剧情，接管小游戏 | `{"action":"plot","enabled":false,"ocr":false}` |
| 取得控制权，需客户端 `--owner` | `{"action":"claim"}` |
| 释放控制权并释放输入 | `{"action":"release"}` |
| 查询控制器状态，不激活游戏 | `{"action":"status"}` |
| 结束本轮控制，不激活游戏 | `{"action":"stop"}` |
| 启动游戏并进入可操作状态，单独提交 | `{"action":"start_game","ocr":false}` |
| 沿已标定路线到达指定点位 | `{"action":"navigate","route":"assets/treasure_routes/life_sciences_institute/ecopark-south.json","target":"4741","observe":false}` |

批次使用 `{"actions":[...],"ocr":false}`，末尾观察一次；绝对坐标点击、拖动等还需在批次前截图更新坐标，纯按键、移动与相对转镜头无需这次截图。后续立即还有已确定动作时可用 `"observe":false` 省掉末尾截图与 OCR；未知路线的移动仍保留末尾观察。示例中的时长和镜头增量只作起点，按当前环境校准。

`navigate` 复用同一进程内的 `TreasureGame` 和地图定位器，载入普通点位路线，执行准备步骤、区域和起点核验，再依序走到 `target`。目标必须存在于路线中；不接受任意步骤切片，不支持巡回扫描路线。结果在 `actions` 中返回 `navigation_status: arrived`、目标和耗时；导航不调用开箱，也不证明活动或奖励完成。角色、镜头、楼层和分辨率仍须符合路线标定条件。

主界面与地图之间的 `screen` 切换每次按键后最多等待 4 秒。开图超时且重新确认仍在主界面时，只补按一次地图键；未知界面、再次超时或退出地图失败均停止并返回错误，不重复按 Esc。其他界面沿用小助手的界面管理器。

只需文字判断时配合 `ocr_region` 和 `save_image:false`，省掉 PNG 编码与写盘；仍会截图供 OCR 使用。需要看图或确认陌生布局时保留默认图片输出。纯观察、等待、状态与停止请求不再额外等待固定的 0.3 秒；手动输入默认保留这段稳定时间。若批次末尾已有足够的 `wait`，可显式设置 `settle:0`，避免叠加等待。

手动输入会停止自动剧情，且不会在批次结束后自行恢复；返回剧情阶段时显式发送 `plot` 开启指令。旧会话尚未采用该行为时，先显式关闭剧情再接管特殊玩法。普通战斗仍需从画面确认自动与加速已打开。输入动作可加 `wait` 等待界面变化；等待时间按阶段选择，避免长时间阻塞调用。

客户端默认等 25 秒。返回 `pending` 时保留 `request` 编号，用 `--result 0001` 查询同一请求，**不能重新提交相同动作**。结果中的 `image`、`texts` 和 `records` 对应该请求的执行后状态；`--compact` 仅省略终端中的文字坐标，完整记录仍在会话目录。新进程遇到上一轮未完成的请求会标记 `interrupted`，先观察现状再决定下一步，不自动重放输入。

请求文件由客户端在短文件锁内分配新编号并原子提交，避免并发客户端覆盖请求；已提交文件不可改写。同一进程记住已处理编号，空闲时只检查请求目录是否变化，避免随历史记录增加而反复扫描所有结果。查询结果继续使用 `--result`。

兼容接续旧会话时，以其现有脚本能力为准：旧版可能没有 `status` 动作与 `observe:false`，但可以用新入口的 `--status` 查存活，并用客户端发送原有的截图、点击与剧情操作。为保留本轮授权，不为新增可选功能专门重启旧进程；新会话自然使用更新后的脚本。

## 路线诊断入口

`treasure_steps` 接收 `route`、`part:"setup"` 或 `chest` 索引，以及可选 `start/end` 步骤切片；`treasure_action` 接收单个 `step`；`treasure_open` 调用现有开箱确认。它们用于局部实测，切片执行没有完整路线的准备和起点保证，不能据此报告整条路线通过。加 `scan:true` 会复用移动分段后的开箱扫描，并返回每次扫描前的实际方向键/Shift 状态和扫描耗时。

`map_locate` 是只读定位入口，接收底图 `image`、`metadata` 路径（相对源码目录或绝对路径），可选 `markers` 和 `require_player`；当前画面须已打开正确地图。它复用地图定位器，返回 `player.reference` 和 `quality`，不自动打开地图或移动。

## 收尾与退出

- 用户要求关闭游戏时，先保存已确认的完成状态，停止自动剧情并释放按键，再发送游戏的正常关闭操作。退出动作使用当前接口支持的 `observe:false`，避免游戏已关闭后仍等待截图；最后发送独立的 `stop` 请求结束本轮控制器。
- 关闭游戏后的核验改用对应进程是否退出、控制器状态或退出记录。不要为确认退出继续截图、激活窗口或重新启动游戏。工具超时可能发生在动作后的观察环节，先检查进程，不能直接重发退出动作。
- 自建或修改控制器时，让 `status`、`stop` 在游戏窗口检查、输入准备和截图之前处理；退出路径释放按键、停止自动剧情并清理本轮资源，即使游戏窗口已消失也能完成。不要把畸形请求或故意触发异常当作正常退出协议。
- 接续旧控制器时先核对其实际退出能力。需要终止残留进程时，只处理已确认属于本轮的进程及子进程；不按通用进程名批量结束其他 Python 或小助手任务。
