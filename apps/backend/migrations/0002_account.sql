-- 0002_account —— 注册/登录用的账号表
--
-- consent_record.user_id 有意不加外键：账号删除后 consent_record 要匿名化保留
-- （P0-07 §7 / B1，user_id 替换为不可逆哈希），外键会挡住这件事。

CREATE TABLE account (
    id             uuid PRIMARY KEY,
    email          text NOT NULL,
    password_hash  text NOT NULL,
    created_at     timestamptz NOT NULL,
    updated_at     timestamptz NOT NULL
);

CREATE UNIQUE INDEX account_email_lower_idx ON account (lower(email));
