from langchain.agents.middleware import AgentMiddleware



#根据请求的request_skills动态更新skills_metadata
class DynamicSkillsMiddleware(AgentMiddleware):



     def before_agent(self, state, runtime):

        skills = state.get("skills_metadata", [])
        request_skills = runtime.context.get("request_skills",[])
        skills_metadata = [
                s for s in skills
                if s['name'] in request_skills
            ]
        return {"skills_metadata": skills_metadata}
