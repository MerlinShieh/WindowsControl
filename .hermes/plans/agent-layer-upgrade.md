# Agent 层升级规划 — 把真机验证的内核能力接入产品工具集

> 日期:2026-08-11
> 背景:内核感知/输入/验证层已经历大量真机验证(Lock 前台锁定、行级点击、
> GPU OCR、稳定验证、托盘态边界),但 agent.py 工具集仍是旧前台路径。
> 本次升级 = 让产品真正用上内核新能力。

## 一、现状问题(agent.py 旧工具集)

| 工具 | 现状 | 问题 |
|---|---|---|
| `click_text` | `locate_text_on_screen` 全屏定位 + `wc_input.click` 前台点击 | ① 前台点击抢焦点 ② 全屏 OCR 慢(9s) ③ 无稳定验证 |
| `type_text` | `wc_input.type_text` 前台输入 | 抢焦点 |
| `look_screen` | 全屏截图 + OCR + 视觉 | 全屏慢;无窗口级选项 |
| 缺 `click_row` | — | 微信列表这类行级界面无法精确操作 |
| 缺窗口目标 | — | 所有工具都"全屏",无法指定"在XX窗口里操作" |

## 二、升级目标

1. **全部后台化**:click/type 默认 `foreground_lock` + post_click/type_text_bg(不抢焦点)
2. **窗口级定位**:工具支持 `window` 参数,优先 PrintWindow+窗口内 OCR(快、准、免遮挡)
3. **行级能力**:新增 `click_row`(列表项点击)
4. **稳定验证**:操作前 `wait_stable`,操作后截图对比
5. **保持 API 兼容**:LLM 工具定义更新,旧调用(如"点击发送")语义不变

## 三、具体改动

### 3.1 新增工具 `click_in_window`
```
参数: window(str, 窗口标题), text(str, 要点的文字)
逻辑: find_windows → PrintWindow 抓窗口 → OCR 定位文字 → click_row(后台+Lock)
返回: ok, clicked, window_rect, center, 后台? 
```

### 3.2 新增工具 `click_row`
```
参数: window(str), text(str, 行内任意文本, 会话名/预览均可)
逻辑: PrintWindow → cluster_rows → locate_row_in_window → click_row(后台+Lock)
适用: 微信/QQ/文件管理器等列表界面
```

### 3.3 改造 `click_text`(保持名称,升级实现)
```
定位: 全屏 OCR(locate_text_on_screen)→ 多匹配视觉消歧(保留)
点击: 前台 click → 改为 foreground_lock + post_click(后台)
验证: 可选 verify
```

### 3.4 改造 `type_text`(保持名称,升级实现)
```
前台 type_text → foreground_lock + type_text_bg(后台)
新增 window 参数: 输入前先点击目标窗口/输入框
```

### 3.5 新增工具 `list_windows`
```
参数: filter(可选)
逻辑: enum_windows → 标题/进程/可见性列表
用途: LLM 先查有哪些窗口,再精确操作
```

### 3.6 升级 `look_screen`
```
新增 window 参数: 指定窗口则 PrintWindow 抓该窗口(快),否则全屏
```

### 3.7 系统提示词更新
```
- 告诉 LLM 优先用 window 参数精确定位(后台操作)
- click_row 用于列表;click_in_window 用于窗口内文字
- 强调后台化:工具自动 Lock 前台,无需 LLM 关心
```

## 四、测试计划(TDD)

1. `test_agent_tools.py`(新):mock 内核,验证各工具:
   - click_in_window 正确调用 find_windows+ocr_window+click_row
   - click_row 正确调用 cluster_rows+click_row+Lock
   - click_text 升级后走 post_click(不抢焦点)
   - type_text 升级后走 type_text_bg
   - 工具参数缺省/错误处理
2. 现有 test_agent.py 回归(工具名/签名兼容)
3. 真机:微信"点会话→输入→发送"通过 Agent 工具组合完成(端到端)

## 五、范围与边界

- 本次只做 Agent 工具层,不动 commands.py(快速路径)
- 视觉消歧逻辑保留(多匹配场景仍需要)
- 游戏防护/危险分级逻辑不动(agents 调 commands,已有 L0-L3)

## 六、验收标准

- [ ] 96 现有测试 + 新增工具测试全绿
- [ ] LLM 用新工具集能在微信上完成"点会话→输入→发送"且全程后台
- [ ] 无前台窗口切换(Lock 生效)
