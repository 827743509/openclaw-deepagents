use langgraph
db.createCollection("agent_conversations")
// thread_id 全局唯一
db.agent_conversations.createIndex(
    { thread_id: 1 },
    {
        unique: true,
        name: "uk_thread_id"
    }
)

// 查询某个用户 + 某个 Agent 的会话
db.agent_conversations.createIndex(
    {
        user_id: 1,
        agent_name: 1,
        created_at: -1
    },
    {
        name: "idx_user_agent_created"
    }
)

