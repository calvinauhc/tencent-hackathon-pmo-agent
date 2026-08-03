Agent 1: To read either from email or form template and parse the request (Submitter name and team members, Objective/pain point, project name, solution, Business impact in terms of size of price, hypothesis risk for example regulatory, CAPEX needed).
Agent 2: To use the parse results and check existing record using LLM to query postgres on the pain point for similar project
Agent 3: If yes, reply to requester that it has been rejected and provide the originator to further connect
Agent 4: If no, email to PMO for notifications and PMO can decide to activate Agent 5 manually via email (Proceed or Reject or Review)
Agent 5: To analyse the business impact i.e financials margins, Size of price, reference from Playbook with the help of Agent 6, and provide the insights to PMO for review.
Agent 6: Pull out from Knowledge management (RAG + CAG) and using LLM to cross check the playbook/core value/ ethics
Manual intevention: Project Management Office will manually intervene and authorise to proceed or reject with suggested comments. For example, low margins, not align with the strategic directions, high regulatory risk, incomplete information
Agent 7: If accepted, engage A3 to reply and issue a project ID and create a record into Postgres
Agent 8: If rejected, will use stakeholder comments to provide valid reason or improvement areas to the requestor. 
Agent 9: Dashboard available for internal distribution: (Technical team: Operations, Regulatory, Quality, Engineering, Research & Development and Commerical team: Finance, sales, marketing)
- Present the list of project by region by Business unit, Size of price (USD), risk indicator (Green/Yellow/Red), Critical Path Schedule status (Green/Yellow/Red), CAPEX tracker (USD and % towards full funding, building block/ help needed (open text). 
Manual intevention: Each stakeholders can propose their concerns if they find misalignment with the company directions or better solution, or new risk or opportunity. This allow PMO to relook at the scope to avoid any scope creep. PMO will issue a new project ID after Change management is approved. PMO can include if there are any resource constraint or adjustment needed.
Agent 10: Prediction on project success can be based on the financial tracking, Milestone tracking, Resource tracking and risk indicators. If the measurements are on track, the higher prediction score will be for successful launch.

Trial documents needed:
1) 100 entries of projects in differnt phases that needs to be recorded via postgres; indicating Submitter name and team members, Objective/pain point, project name, solution, Business impact in terms of size of price, hypothesis risk for example regulatory, CAPEX needed.
2) 1 page of Company playbook to present the business context, the region to focus, the product or technology to invest
3) 1 page of Company PVP document including Core values, ethics, and working principle.

Scenarios needed for testing the system:
1) Create new project entry, 
- 1 accepted with aligned business direction, low capex and high size of price, 
- 1 rejected due to similar project existed, 
- 1 rejected due to not align with business direction, 
- 1 under review due to unknown regulatory risk

