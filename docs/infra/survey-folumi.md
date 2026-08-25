# Folumi 基础设施调研报告

调研对象：`../Folumi`（Tauri 桌面 Agent 应用，记忆/Notebook/Session Recall 参考实现）。

## 1. 整体架构

```
Folumi = Tauri 桌面壳 + AXUM Web 后端 (tutor-web) + llm-harness-runtime
├── src-tauri/          Tauri 壳, sidecar 拉起 tutor-web
├── crates/tutor-web/   AXUM 后端: memory_store, memory_runtime, session, notebook, routes
├── crates/tutor-agent/ Agent 构建: runtime_harness, chat, knowledge, capability
├── crates/tutor-rag/   LanceDB 知识源
└── web-ui/             React + TypeScript + Tailwind
```

## 2. Saved Memory 实现 (memory_store.rs, 1363 行)

**这是 Studio 决策记忆的直接参考实现。**

### 2.1 SQLite 表结构

```sql
CREATE TABLE memory_items (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('fact','preference','goal','continuity')),
    content TEXT NOT NULL,
    topic_key TEXT,
    status TEXT NOT NULL CHECK(status IN ('active','resolved','superseded')),
    priority TEXT NOT NULL CHECK(priority IN ('normal','pinned')),
    origin TEXT NOT NULL CHECK(origin IN ('user_explicit','assistant_suggested')),
    provenance TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    last_confirmed_at TEXT NOT NULL, valid_until TEXT, resolved_at TEXT,
    revision TEXT NOT NULL
);
CREATE TABLE memory_relations (
    from_id TEXT, relation_type TEXT CHECK(relation_type IN ('supersedes')),
    to_id TEXT, PRIMARY KEY(from_id, relation_type, to_id)
);
CREATE TABLE memory_history (memory_id, revision, operation, prior_value, changed_at, origin);
CREATE TABLE memory_idempotency (policy_scope, idempotency_key, result_id, result_revision, created_at);
CREATE TABLE memory_tombstones (id TEXT PRIMARY KEY, deleted_at, content_hash);
CREATE VIRTUAL TABLE memory_items_fts USING fts5(memory_id UNINDEXED, content, topic_key);
```

### 2.2 关键机制

| 机制 | 实现 |
|---|---|
| CAS (revision) | 每次变更生成新 revision，不匹配返回 Stale |
| supersede 事务 | BEGIN IMMEDIATE + 旧条目 superseded + 新条目创建 + relations 记录 |
| topic_key 冲突 | find_topic_conflict → Reject/Replace/KeepBoth |
| 写入授权 | origin: user_explicit/assistant_suggested + approval flow |
| idempotency | idempotency_key + policy_scope 唯一约束 |
| tombstones | 遗忘只保留 id + 删除时间 + 不可逆内容摘要 |
| schema migration | v1→v2→v3, PRAGMA user_version |

## 3. Memory Runtime 适配

```
SavedMemoryKnowledgeSource (读) → KnowledgeSource trait → knowledge_search/read
SavedMemoryWriteStore    (写) → MemoryStore trait     → memory_write/forget
SavedMemoryApprover           → 审批流程
```

组装链：`MemoryService(access_control, read_source, write_store, write_policy, mutation_gate)` → `MemoryPlugin`

## 4. Session Recall

```
SessionPool = JsonlSessionRepo (权威) + SqliteSessionRecallIndex (FTS5 投影)
├── history_recall_enabled 独立开关, 默认关闭
├── 临时对话不索引、不召回
├── 删除 Session → 同步删索引
├── 索引损坏 → 从 Session 权威源重建
└── ObservedSessionRepo → SessionMutationObserver → SessionRecallProjector 增量更新
```

## 5. 设计文档要点 (user-memory-redesign)

**文件**：`specs/2026-08-03-user-memory-redesign.md`

- 退役旧 L1/L2/L3 分层模型
- 双通道：Saved Memory（显式、可编辑）+ History Recall（可选、按需）
- Memory 是全局的，不按 session/workspace 分区
- 写入只有三条路径：用户明确说"记住"、用户直接陈述+助手提议、用户手动新增
- 助手不得从模糊暗示中推断

## 6. Knowledge 系统

**文件**：`crates/tutor-agent/src/knowledge.rs`

- `LocalDocumentSource` — 本地 Markdown/Text, BM25 搜索, CJK 逐字 token
- `tutor-rag` — LanceDB 向量知识源
- 多源联邦搜索（逐源 authorize）

## 7. Studio 可借鉴要点

| 模式 | 来源 | Studio 用途 |
|---|---|---|
| SQLite+FTS5+CAS+supersede | memory_store.rs | 决策记忆的 Python sqlite3 重新实现 |
| topic_key 冲突解决 | memory_store.rs | 按 step:classify 维度的决策冲突处理 |
| idempotency + tombstones | memory_store.rs | 防重复写入 + 可审计的遗忘 |
| schema migration | memory_store.rs | 记忆 schema 演进 |
| MemoryService 组装链 | memory_runtime.rs | SDK MemoryPlugin 接入方式 |
| Session Recall 双通道 | session 模块 | 跨对话搜索参考 |
