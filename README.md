# Apple MacBook Pro M5 价格监控

每天北京时间 09:00 用 **Python 3.12 + Playwright Chromium** 打开 [Apple 中国目标商品页](https://www.apple.com.cn/shop/buy-mac/macbook-pro/14-inch-space-black-standard-display-apple-m5-chip-10-core-cpu-10-core-gpu-24gb-memory-1tb-storage)，核对 14 英寸、M5 10 核 CPU / 10 核 GPU、深空黑色、标准显示屏、24GB 内存、1TB SSD、70W 适配器、带触控 ID 的中文（拼音）键盘。只从渲染后的购买摘要内标记为 `fullprice` 的组件读取人民币一次性售价。不会采用起售价、分期、优惠、翻新、折抵或 AppleCare+ 价格。

**未经真实浏览器验证，不提供价格。** 每次运行生成 `evidence/<北京时间>/result.json`，只有全部核对成功才是 `verified: true`，也只有成功记录才追加到 `price_history.jsonl`。

## 文件

- `price_check.py`：访问、选配核对、价格提取、证据保存、历史比较。
- `test_price_check.py`：防止误收起售价、分期或未确认的键盘。
- `requirements.txt`：固定 Playwright 版本。
- `price_history.jsonl`：跨天保存已验证价格；比较上一条时只使用相同商品 URL 的记录，旧 M5 Pro 记录予以保留。
- `.github/workflows/price-check.yml`：定时及手动云端运行。

## 本地运行

安装 Python 3.12 后，在本项目目录执行：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
PLAYWRIGHT_BROWSERS_PATH=.browsers .venv/bin/python -m playwright install chromium
PLAYWRIGHT_BROWSERS_PATH=.browsers .venv/bin/python -m unittest -v
PLAYWRIGHT_BROWSERS_PATH=.browsers .venv/bin/python price_check.py
```

Windows 请将 `.venv/bin/python` 换成 `.venv\\Scripts\\python.exe`。无图形界面的 Linux 可直接使用无头 Chromium。

## 部署到 GitHub

1. 将修改推送到已配置的 GitHub 仓库。
2. 在仓库 **Settings → Actions → General → Workflow permissions** 选择 **Read and write permissions**，使成功记录能提交到 `price_history.jsonl`。如果默认分支受保护，允许 GitHub Actions 写入，或改用有权限的持久存储。
3. 打开 **Actions → Apple MacBook Pro M5 price check → Run workflow** 手动实测。检查运行日志和 `apple-price-evidence-<运行编号>` 附件中的 `result.json`、截图、页面结构及网络日志。确认 `verified: true` 后再依赖定时运行。

定时表达式是 UTC `0 1 * * *`，对应全年北京时间 09:00；中国大陆不实行夏令时。GitHub 的定时任务可能在高负载时延迟启动，实际查询时间以 `result.json` 为准。电脑无需开机。

## 证据和历史

每次运行尽可能保存完整页面截图 `page.png`、`page.html`、DOM/选项 `dom.json`、`configuration_summary.txt`、`network.jsonl`、`errors.log`、`result.json`。Actions 上传证据和运行输出 `run.log`，保留 90 天。浏览器在启动前失败时无法截图，`result.json` 和日志会说明原因。

`price_history.jsonl` 由成功的 Actions 运行提交到仓库，保存历次已验证售价及相对同一商品上一条成功记录的差额。失败运行不会覆盖历史价格，也不会记录猜测值。

## 故障排查

- **`browser_started: false`**：查看 `errors.log`。本机可能无法下载或启动 Chromium；在 Actions 的 Ubuntu 环境重新运行，并查看浏览器安装步骤及启动错误。
- **键盘或其他配置核对失败**：查看 `dom.json` 中 `serverSelections`、`choices` 和 `summary`。Apple 页面结构变化后，更新 `DOM_SCRIPT` 的提取规则和 `verify()` 的校验；不要放宽为仅凭 URL 猜测。
- **价格无法核实**：检查 `summary[].priceNodes` 与截图。只有最终购买摘要的全额价格组件可用。若 Apple 改名或改变组件结构，依据新页面证据修改选择器并新增对应测试。
- **验证码或访问限制**：程序会失败并保存可取得的证据；不要绕过限制。
- **历史未更新**：查看 `Persist verified history` 步骤以及仓库 Actions 写权限和分支保护规则。失败查询不写历史是预期行为。
