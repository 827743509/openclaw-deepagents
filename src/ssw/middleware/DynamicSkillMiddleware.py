from langchain.agents.middleware import AgentMiddleware



class DynamicSkillsMiddleware(AgentMiddleware):



     def before_agent(self, state, runtime):

        skills = state.get("skills_metadata", [])
        request_skills = runtime.context.get("request_skills",[])
        state["skills_metadata"] = [
                s for s in skills
                if s['name'] in request_skills
            ]
        return state