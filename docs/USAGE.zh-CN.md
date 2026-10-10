# IECHO 法国获客 MVP

此工具用于内部管理法国包装、PLV 广告展示、大幅面印刷企业。核心系统是未修改的 EspoCRM；采集基于 Google Maps Scraper，带有小范围依赖兼容修复：恢复 TLS 校验并支持无密码代理。行业适配和采购意向需要人工核实。

## Windows 使用

安装并启动 Docker Desktop（Linux 容器），安装 Python 3.10 或更新版本。解压交付包后，在项目目录的 PowerShell 中运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\Start.ps1
```

这里的执行策略只作用于此次脚本进程。脚本生成本机专用密码，构建修复版采集镜像，启动服务并配置字段，不会发送邮件。第一次需要下载镜像、源码和编译依赖，建议至少预留 20GB Docker 磁盘空间。启动后会打开本机 CRM 浏览器窗口；本机 8082 端口是采集界面。用户名 admin；密码在本机 `.env` 文件的 `CRM_ADMIN_PASSWORD` 中。交付包不含云机器密码、云代理证书或 CRM 数据库；GitHub 下载包不含真实客户名单；可自行采集后导入。PowerShell 启动脚本已编写，但没有在 Windows 机器实测。

## 云机器启动

```bash
cd /workspace/-
python tools/mvp.py init
export DOCKER_CONFIG=/workspace/-/runtime/docker
mkdir -p "$DOCKER_CONFIG"
# 仅在修复版镜像缺失时编译，已存在则复用。
docker image inspect iecho/maps:1.18.1-verified >/dev/null 2>&1 || IECHO_MAPS_BUILD_DIR=/tmp/iecho-maps-build python -u tools/build_maps.py --native
docker compose -f compose.yaml -f compose.cloud.yaml --profile maps up -d
python tools/mvp.py setup
python tools/mvp.py health
```

本云环境没有已验证的浏览器访问入口；内部请求可以验证服务。Windows 本地运行是可提供给你操作的方案。进程不随环境发布保留，后续任务应按启动步骤重启服务。使用现有 checkout，不要创建 Git worktree。

本云环境使用 vfs Docker 驱动，镜像层会复制而不是共享；修复版采集镜像已压平，保留相同二进制和证书信任。`build_maps.py` 在 vfs 上会自动执行这个优化。其他 Docker 驱动正常复用层即可。首次失败安装的旧 CRM 卷保留完整；清理空间仅处理了构建缓存、已备份的浏览器缓存及可重新下载的镜像。

## 1. 收集候选企业

在采集界面创建任务，一次一个行业和城市；法语示例见 `data/france-queries.txt`。首轮低并发、小范围运行，下载 CSV。Maps 有搜索范围和覆盖率限制，不能视为法国全量企业名单。公开邮箱提取不保证拿到采购负责人邮箱。也可将展会或行业目录名单填入 `data/import-template.csv`。

也可运行以下命令，以法国城市坐标创建标准浏览器采集任务。云机器会复用环境 HTTPS 代理，Windows 没有代理变量时使用正常联网：

```powershell
python tools/mvp.py search "impression grand format Lyon" --city Lyon
# 用上一步返回的任务 ID 替换下面的占位符，任务完成后再下载。
python tools/mvp.py download "任务ID"
```

任务创建不表示采集成功。下载命令检查完成状态及有效企业行数，空文件会报错，不会冒充可用名单。第一次搜索至少允许约三分钟。此版本没有自动判断行业与机器适配。

## 2. 导入并去重

先检查导入结果，再真正导入：

```powershell
python tools/mvp.py import "你的名单.csv" --dry-run
python tools/mvp.py import "你的名单.csv"
```

支持 Maps 的 title、website、phone、emails、link、address 列，以及模板中的 company、website、email、phone 等列。country 列缺失时标记为法国候选，必须核对地址。非法国记录、无公司名和错误枚举等会阻止整份文件导入。首次导入的跟进阶段都是“À qualifier”。

去重按规范化域名、邮箱或公司名＋国家判断；重复只跳过，不覆盖已有跟进或拒绝联系状态。一个域名暂时只保留一条公司级线索，集团的多个分支会被合并处理。导入工具一次运行一个进程；网络中断后可重跑。

在 CRM 的 Leads/销售线索模块打开记录，“法国获客 / Prospection France”面板包含材料、设备、依据、证据网址、来源、角色、跟进阶段、下次跟进和草稿字段。可在列表的列设置中选择这些字段并筛选。

## 3. 人工核实设备适配

优先包装打样、纸板包装、PLV 制作、大幅面印刷后加工。填写真实材料和证据网页，区分生产厂、经销商及不生产的设计公司。

| 设备 | 官网明确应用 | 核查要点 |
|---|---|---|
| PK / PK4 | 标识、印刷、包装打样与短单 | 是否打样、压痕、印刷后裁切 |
| BK / BK4 | 单层/少层、多工具加工 | 材料、刀具、铣削/开槽需求 |
| TK4S | 大幅面加工 | 实际材料幅宽、印刷定位和刀具 |
| GLSC | 纺织、家具、汽车内饰多层裁切 | 不与包装客户混用名单 |

官网来源见 `config/france.json`。材料厚度和幅宽上限取决于具体机器与刀具，不能把某个工具的极限当作全系列承诺。证据链接只是销售填写的依据，工具不会验证页面内容或自动判断采购需求。

核实后将跟进阶段设为 `À contacter`，确认不是演示数据、已拒绝联系或不适合客户。

## 4. 生成法语草稿并人工发送

从 CRM 记录地址中的记录 ID 取值，运行：

```powershell
python tools/mvp.py draft "记录ID"
```

草稿会写回 CRM 的主题与正文，**不发邮件**。没有证据、材料、适配设备或审核状态会拒绝生成；演示记录与拒绝联系记录也会被拦截。此版本采用确定性模板，不需要模型 API 密钥。

草稿包含待替换的真实销售身份和公司信息。审核事实与签名后，用现有邮箱人工发送。对方拒绝联系时将阶段设为 `Ne pas contacter`，同步维护现有邮箱中的拒绝联系名单。实际联系条件仍须按收件人所在市场核实。

## 5. 跟进与验收

阶段依次为待筛选、待联系、已联系、已回复、已报价、不适合、拒绝联系。`cNextFollowUp` 是人工管理的日期字段，首版没有自动提醒或自动发信。

约 100 家候选企业是下一步市场验证目标，不是已采集结果。关注人工确认的适配数量、可用联系方式和有效回复。

`data/demo.csv` 仅含虚构企业和保留的 `.example` 域名，用于验证导入。运行 `python tools/mvp.py import data/demo.csv --demo` 可导入，两条都明确标记为演示，不能生成邮件草稿。

## 停止、备份与升级

`docker compose --profile maps stop` 停止服务并保留数据。正常重启使用 Start.ps1 或上述云机器命令。不要运行带 `-v` 的 down 命令，它会删除客户数据库。

配置在项目文件和 `.env`，客户数据在 Docker volumes；复制代码不等于备份数据库。CRM 管理员可通过原生导出功能导出客户，完整备份需要同时备份数据库与附件卷。镜像版本和摘要已固定，升级前应备份并测试。

本版没有公网部署、SMTP 配置、付费线索 API、AI 自动评分或自动化群发。

## 开源来源

- EspoCRM 10.0.9：https://github.com/espocrm/espocrm ，AGPLv3；保留原界面和法律声明。
- Google Maps Scraper v1.18.1：https://github.com/gosom/google-maps-scraper ，MIT。固定源码提交、下载校验和在 `config/maps-sources.json`。
- EspoCRM 通过官方管理 API 与 REST API 配置和集成，没有修改其核心代码。
- 采集依赖 scrapemate 做了明确的源码修复；补丁由 `tools/prepare_maps.py` 应用于临时构建副本。保留上游许可，不使用跳过证书验证的原版浏览器参数。新增代理及 TLS 行为测试在 `config/maps_*_test.go`。
