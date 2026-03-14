# Apify Actor vs CafeScraper Worker 对比说明

用通俗说法对比如下。

---

## 一、本质区别（一句话）

- **Apify Actor**：跑在 Apify 自己的云上，用 Apify 的「遥控器」（SDK）拿输入、写日志、存结果。
- **CafeScraper Worker**：跑在 CafeScraper 的云上，用他们的「遥控器」（gRPC SDK）拿输入、写日志、交结果。

也就是说：**同一套爬虫逻辑，只是接的「平台接口」不一样**，所以要加的文件和入口写法不同。

---

## 二、各自要「加什么文件」

### 1. 改成 Apify Actor 需要加的

| 要加的东西 | 作用 |
|-----------|------|
| **`.actor/actor.json`** | 告诉 Apify：这个 Actor 叫什么、用啥环境、内存/超时等。 |
| **`.actor/input_schema.json`** | 在控制台里画出「输入表单」（关键词、国家、页数等）。 |
| **`.actor/output_schema.json`** | 说明结果存在哪（默认 dataset）、API 里怎么看到。 |
| **`.actor/dataset_schema.json`** | 可选，定义结果表格在控制台里怎么展示（列名、格式）。 |
| **Dockerfile** | 把 Python + 依赖打成镜像，在 Apify 的容器里跑。 |
| **依赖里加 `apify`** | 代码里用 `Actor.get_input()`、`Actor.push_data()`、`Actor.log` 等。 |

入口脚本里：**用 Apify SDK** 拿输入、打日志、推送数据，例如：

- 输入：`await Actor.get_input()`
- 日志：`Actor.log.info("...")`
- 存结果：`await Actor.push_data({...})`

**浏览器**：在 Apify 的容器里自己起浏览器，需要镜像里能跑 Chromium（或先 `playwright install chromium`）。

---

### 2. 改成 CafeScraper Worker 需要加的

| 要加的东西 | 作用 |
|-----------|------|
| **`sdk.py`** | 封装「怎么跟平台说话」：取输入、设表头、推送一行行数据、打日志。 |
| **`sdk_pb2.py`** + **`sdk_pb2_grpc.py`** | gRPC 自动生成的代码，底层真正发请求到平台（127.0.0.1:20086）。 |
| **`input_schema.json`**（根目录） | 平台用来自动生成输入表单；格式与 Apify 不同（见下）。 |
| **依赖里加 `grpcio`、`protobuf`** | 因为 SDK 是靠 gRPC 和平台通信的。 |

入口脚本里：**用 CafeSDK**，例如：

- 输入：`CafeSDK.Parameter.get_input_json_dict()`
- 先设表头：`CafeSDK.Result.set_table_header(headers)`
- 再逐行推送：`CafeSDK.Result.push_data(row)`
- 日志：`CafeSDK.Log.info("...")` 等。

平台会负责把输入通过 gRPC 塞给你，你把结果再通过 gRPC 推回去。

**浏览器**：**不在本机起 Chromium**。按官方推荐用 Playwright 的 **CDP 连接平台的远程指纹浏览器**：`playwright.chromium.connect_over_cdp("ws://{PROXY_AUTH}@chrome-ws-inner.cafescraper.com")`，环境变量 `PROXY_AUTH` 由平台注入。因此无需在运行环境里安装 Chromium 或执行 `playwright install`。详见 [Why Use Playwright](https://docs.cafescraper.com/why-use-playwright)。

**input_schema.json 格式**：与 Apify 不同，根级是 `description`、`b`（任务拆分键，填某个参数的 `name`）、`properties`（**数组**）。每项用 `name`、`title`、`type`、`editor`（如 `stringList`、`select`、`number`、`switch`）等。关键词列表用 `editor: "stringList"`，默认值形如 `[{"string": "xxx"}]`。详见 [UI模板配置文件 (input_schema.json)](https://docs.cafescraper.com/cn/actor/actor/input_schema.md)。

---

## 三、对比小结（「有什么不同、要加什么」）

| 维度 | Apify Actor | CafeScraper Worker |
|------|-------------|---------------------|
| **跑在哪里** | Apify 云、容器 | CafeScraper 云（脚本/Worker 环境） |
| **和平台怎么通信** | 用 Apify 的 Python 库（HTTP/内部 API） | 用 gRPC，连本机 127.0.0.1:20086（平台在旁起本地服务） |
| **配置/元数据放哪** | `.actor/` 下多个 json + Dockerfile | 根目录 `input_schema.json` + 三个 SDK 文件 |
| **必须多出来的文件** | `.actor/*`、Dockerfile、依赖 `apify` | `sdk.py`、`sdk_pb2.py`、`sdk_pb2_grpc.py`、依赖 grpcio/protobuf |
| **结果怎么交** | `Actor.push_data(item)`，平台自动存 dataset | 先 `set_table_header`，再对每一行 `push_data(obj)`，key 需与表头一致 |
| **浏览器/运行环境** | 容器内自己起 Chromium（需能安装或预装） | **不装 Chromium**；用 `connect_over_cdp` 连平台提供的远程指纹浏览器（`chrome-ws-inner.cafescraper.com`），依赖 `PROXY_AUTH` |

所以：

- **改造成 Apify Actor** = 加 `.actor/` 配置 + Dockerfile + 用 Apify SDK 把脚本「接到」Apify，并在镜像/环境中解决 Chromium 运行。
- **改造成 Worker** = 加三个 SDK 文件 + 根目录 `input_schema.json`（CafeScraper 格式）+ 用 CafeSDK 把脚本「接到」CafeScraper，并用 CDP 连平台浏览器，不装本地 Chromium。

---

## 四、Worker 这边和 Apify 的差异（通俗讲）

- **文档/约定**：Apify 的 Actor 规范、输入输出、部署流程文档很完整；CafeScraper 有 [Script 目录结构](https://docs.cafescraper.com/Template-directory-structure)、[input_schema](https://docs.cafescraper.com/cn/actor/actor/input_schema.md)、[Why Use Playwright](https://docs.cafescraper.com/why-use-playwright) 等，约定在逐步统一，但和 Apify 的 schema 不通用，需要按平台文档来写。
- **部署/运行方式**：Apify 是「镜像 + 配置」的流水线；CafeScraper 是「传脚本 + 依赖」，平台拉代码、装依赖、注入 `PROXY_AUTH` 等，浏览器用 CDP 远程连接，无需在跑脚本的环境里装 Chromium。
- **SDK 形态**：Apify 是官方 Python 包；CafeScraper 是仓库里自带的几个 py 文件（含 protobuf 生成代码），升级、版本兼容需自己留意。
- **输入/输出约定**：例如「必须先 set_table_header 再 push_data、key 要对齐」「input_schema 用 properties 数组和 editor」等，都是平台侧约定，需按 CafeScraper 文档来，和 Apify 的 schema 不兼容。

**改造思路一样**：爬虫逻辑不变，外面包一层「平台 SDK 的输入/输出/日志」；差异在于「加什么文件、入口调什么、浏览器用本机还是 CDP」按各自平台来即可。
