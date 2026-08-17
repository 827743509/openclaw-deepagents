from typing import NotRequired, TypedDict


from langchain.agents.middleware import AgentMiddleware

class DynamicSkillsState(TypedDict, total=False):
    skills_metadata_all: NotRequired[list]

#根据请求的request_skills动态更新skills_metadata
class DynamicSkillsMiddleware(AgentMiddleware):
    state_schema = DynamicSkillsState



    def before_agent(self, state, runtime):

        skills = state.get("skills_metadata", [])
        request_skills = runtime.context.get("request_skills",[])
        skills_metadata = [
                s for s in skills
                if s['name'] in request_skills
            ]
        return {"skills_metadata": skills_metadata,"skills_metadata_all":skills}

    #结束把原先存入skills_metadata_all的全部skills还原到skills_metadata
    def after_agent(self, state, runtime):

        skills = state.get("skills_metadata_all", [])

        return {"skills_metadata": skills}
