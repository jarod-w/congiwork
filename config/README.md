# config/

## scopes.yaml

**授权与审计的唯一事实来源。** 运行时读取，进程启动时校验，校验不过服务起不来。

不要在别处再写一份 Scope 列表 —— 前端从 `GET /api/v1/scopes` 拉，
后端从这里加载。有第二份就迟早不一致。

### 加一个 Scope 要做什么

1. 在 `scopes.yaml` 里加条目，六项元数据齐全（`trust_level` / `risk` / `display_name` /
   `collects` / `retention` / `degraded_behavior`），至少写 `en-US` 文案。
2. `degraded_behavior` 必须是**真实可用的替代路径**。写不出来说明这个能力的
   划分方式有问题 —— 应该重新拆分 Scope，而不是敷衍这一栏。
3. 跑 `pytest`，`tests/guards/` 会检查格式、词表、诱导词、读写分离等。
4. PR 里填 `.github/pull_request_template.md` 的自愿性检查表。
5. 文案送英文母语审校，通过后把 `review_status` 改为 `approved`。

### 不要做的事

- **不要登记还没实现的连接器的 Scope。** 注册表是运行时读取的，
  出现一个点不开的授权项等于欺骗用户。
- **不要给核心路径上的能力加 Scope。**「注册 → 上传文件 → 得到产物」
  这条路径必须零授权可走通（硬约束 5），加 Scope 会让零授权 E2E 挂掉。
- **不要为了「以后方便」一次性申请全权限的第三方 scope。**
  申请的 OAuth scope 必须与我们的 Scope 一一对应。
