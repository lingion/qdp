# UPGRADE NOTES (2026-03)

本轮升级的目标：让下载与本地库维护更“可恢复、可验证、可迁移”。核心是 **Sidecar 元数据落地** + **三阶段并发流水线** + **质量/线路 fallback**。

---

## 1) Sidecar 元数据（全链路落地）

### 写入位置
- 新（优先）：`<album_dir>/.qdp/album.json`
- 旧（兼容读取）：`<album_dir>/qdp_album.json`

### 记录内容（简化摘要）
- 专辑：`album_id / album_title / artist / year`
- 质量：`quality.requested_quality / quality.source_quality / quality.actual_quality / fallback_used`
- 命名：`folder_format / track_format (+ version 字段)`
- 曲目：`track_id / disc / track_number / title / artist / expected_stem / expected_rel_path / actual_file / bit_depth / sampling_rate / source_quality / actual_quality`

### 使用优先级
- `scan-library` / `verify`：优先读取 sidecar 生成 expected track 列表；无 sidecar 时回退 meta + 旧命名 + 标签启发式
- `rename-library`：优先用 sidecar 的 disc/track 映射进行精准迁移（降低误判）

---

## 2) 下载架构：三阶段流水线 + 可配置并发

流水线拆分：
1. album meta：获取并检查专辑元数据
2. prefetch：并发预热 `track/getFileUrl`（**全局限流**）
3. download：并发下载文件 + 标注实际质量 + 指数退避重试

新增参数：
- `--workers`：下载并发
- `--prefetch-workers`：URL 预热并发
- `--url-rate`：track/getFileUrl 全局限速（每秒）
- `--max-retries`：下载最大重试次数
- `--timeout`：单次请求超时
- `--force-proxy`：强制代理，不自动直连兜底

---

## 3) 更优质下载线路与质量 fallback

- 质量 fallback：默认按 `27 -> 7 -> 6 -> 5` 自动降级（可用 `--no-fallback` 关闭）。
- 包装：实际下载质量会写入标签（FLAC: `QDP_QUALITY` / MP3: `TXXX:QDP_QUALITY`），并写入 sidecar 的 `actual_quality`。
- 稳定性：
  - track/getFileUrl：全局 rate limit（避免瞬时压力/代理被打崩）
  - 下载阶段：简单 proxy pool 健康评分 + 冷却；代理全挂后自动直连兜底（除非 `--force-proxy`）

---

## 4) 验证与测试

- 新增/更新 unittest：sidecar 写入/读取（含 legacy 兼容）、scan/rename 优先 sidecar、质量 fallback、pipeline 预热缓存/限流。
- 建议本地运行：

```bash
python3 -m compileall qdp tests
python3 -m unittest discover -s tests -p 'test_*.py' -v
```
