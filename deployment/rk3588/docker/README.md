# RK3588 双模型 CPU PoC

本目录生成两个独立的 Linux ARM64 镜像。每个镜像包含 Agent、Web 操作台、固定版本的 llama.cpp 和一个 Q4_K_M GGUF；运行时不包含编译器、测试、Ollama、声卡或 NPU 组件。两个模型必须串行运行。

## 1. 准备模型

在仓库根目录执行：

```powershell
python deployment/rk3588/docker/prepare_models.py --model all --output models
```

下载器使用 `models.lock.json` 中的官方仓库、固定 revision 和 SHA256。模型授权仅按当前内部研发验证范围处理；扩大分发范围前必须重新审核两个模型的许可证。

## 2. 构建两个 ARM64 镜像包

```powershell
./deployment/rk3588/docker/build_images.ps1 -Model all
```

输出为：

- `dist/rk3588/cloud-flowing-qwen-rk3588-cpu-poc.tar`
- `dist/rk3588/cloud-flowing-lfm-rk3588-cpu-poc.tar`
- `dist/rk3588/SHA256SUMS`
- `dist/rk3588-qwen/`：只包含 Qwen 镜像及其单独校验清单。
- `dist/rk3588-lfm/`：只包含 LFM 镜像及其单独校验清单。

已有镜像无需重建、只重新分包时执行：

```powershell
./deployment/rk3588/docker/build_images.ps1 -Model all -PackageOnly
```

构建使用 llama.cpp commit `69bf643`。在 x86 主机上需要 Docker Buildx 和 ARM64 模拟支持；在 ARM64 主机上可直接构建。

## 3. 交换机安装与自动测试

把对应的单模型目录完整复制到交换机，先测试一个模型：

```sh
sh install.sh qwen /path/cloud-flowing-qwen-rk3588-cpu-poc.tar
```

或：

```sh
sh install.sh lfm /path/cloud-flowing-lfm-rk3588-cpu-poc.tar
```

脚本会先使用同目录的 `SHA256SUMS` 校验镜像 tar，再采集系统、CPU、Docker、内存、磁盘和温度信息；随后以启动档验证，再串行测试 4、6、8 线程的 4096/512 配置。通过条件为固定请求全部完成、连续 10 次请求成功、无 OOM；通过项中 Tokens/s 最高者写入 `selected.env`。最后以最佳线程数测试一次 8192 上下文压力档，并恢复 4096 最佳档长期运行。

结果目录包含：

- `board-probe.txt`
- `benchmark-report.json`
- `selected.env`

默认只监听设备本机 `127.0.0.1:8000`。远程访问可使用 SSH 隧道；仅在可信局域网内，才使用 `POC_BIND_ADDRESS=0.0.0.0 sh install.sh ...` 并访问 `http://设备IP:8000`。停止当前模型使用 `docker stop cloud-flowing-poc`；切换模型时重新运行另一个模型的 `install.sh`，脚本会替换同名 PoC 容器，但保留 Docker 数据卷。完整步骤见 `RK3588-USAGE.md`。

## 配置边界

`LLAMACPP_THREADS`、`LLAMACPP_CONTEXT_SIZE`、`LLAMACPP_MAX_TOKENS`、`LLAMACPP_BATCH_SIZE`、`LLAMACPP_PARALLEL` 都可在不重建镜像的情况下修改。2048/256 只是首次启动档；4096 稳定时应采用自动选出的性能档。8192 只用于压力验证，首轮不测试 32768 上下文或 8192 输出。

当前交付是 CPU PoC 候选。只有 `benchmark-report.json` 来自目标 RK3588 真机时，才能对模型加载时间、TTFT、Tokens/s、峰值内存、CPU、温度和稳定性作验收结论。
