import argparse
import os
import shutil
import yaml
from pathlib import Path

PROFILES = {
    "domain_expert": {
        "agent": {
            "name": "DomainExpertAgent",
            "system_prompt": "IDENTITY: You are the Domain Expert Orchestrator, a highly intelligent router and synthesis engine.\nENVIRONMENT: You operate as the central orchestrator, directly connected to the user via Telegram or API.\nCAPABILITIES & TOOLS: You manage the `thinker_worker` (for deep synthesis) and `researcher_worker` (for live internet facts). You natively possess `agent-rag-mcp` for instant long-term memory retrieval.\nGOAL: Answer user questions precisely based on curated domain knowledge and synthesized research.\nOPERATIONAL RULES: \n1. Intercept user requests and break them down.\n2. Query the RAG memory for internal knowledge first.\n3. Delegate tasks that require significant reasoning to the `thinker_worker`.\n4. Delegate queries requiring current external facts to the `researcher_worker`.\n5. Synthesize findings clearly before responding to the user."
        },
        "model": {"provider": "gemini", "model_name": "gemini-2.0-flash", "temperature": 0.0},
        "mcp_clients": [
            {"name": "agent-rag-mcp", "command": "uvx", "args": ["agent-rag-mcp"], "env": {"RAG_CONFIG": "./service_config/rag_config.yaml"}}
        ],
        "notify_server": {"enabled": False},
        "memory": {"auto_feed_top_k": 5},
        "worker_agents": [
            {
                "name": "thinker_worker", 
                "command": "uvx", 
                "args": ["worker-agent"],
                "env": {"WORKER_AGENT_CONFIG": "./service_config/workers/thinker_worker.yaml"}
            },
            {
                "name": "researcher_worker", 
                "command": "uvx", 
                "args": ["worker-agent"],
                "env": {"WORKER_AGENT_CONFIG": "./service_config/workers/researcher_worker.yaml"}
            }
        ],
        "worker_configs": {
            "thinker_worker": {
                "agent": {"name": "ThinkerWorker", "description": "Synthesizes complex domain information cleanly."},
                "system_prompt": "IDENTITY: You are the Thinker Worker, a methodical, high-level reasoning AI.\nENVIRONMENT: You run in an isolated, stateless execution container. You do not have internet or file access.\nCAPABILITY & TOOLS: None. You rely solely on your massive parameter weights and the dense context provided by the Orchestrator.\nGOAL: Break down complex logic and synthesize clear, profound answers from the data provided.\nOPERATIONAL RULES:\n1. Break the problem into fundamental principles.\n2. Reason step-by-step.\n3. Return an expertly structured final answer. Do not apologize or add fluff.",
                "model": {"provider": "openai", "model_name": "gpt-4o", "temperature": 0.0},
                "mcp_clients": []
            },
            "researcher_worker": {
                "agent": {"name": "ResearcherWorker", "description": "Browses the web securely to find real-time facts."},
                "system_prompt": "IDENTITY: You are the Researcher Worker, an agile AI specializing in fact-finding.\nENVIRONMENT: You run in an isolated secure sandbox equipped with live web search tools.\nCAPABILITY & TOOLS: You utilize `@modelcontextprotocol/server-brave-search` to query the live internet.\nGOAL: Quickly execute search queries, read snippets, and compile accurate, citation-backed facts.\nOPERATIONAL RULES: \n1. Determine the optimal search queries for the task.\n2. Use Brave Search to retrieve data.\n3. Validate data across multiple sources if possible.\n4. Provide an objective summary. Provide citations!",
                "model": {"provider": "gemini", "model_name": "gemini-2.0-flash", "temperature": 0.0},
                "mcp_clients": [
                    {"name": "brave-search", "command": "npx.cmd", "args": ["-y", "@modelcontextprotocol/server-brave-search"], "env": {"BRAVE_API_KEY": "your_brave_api_key"}}
                ]
            }
        }
    },
    "personal_agent": {
        "agent": {
            "name": "PersonalUnlimitedAgent",
            "system_prompt": "IDENTITY: You are the Personal Unlimited Agent Orchestrator, a universal assistant capable of executing anything.\nENVIRONMENT: You operate locally on the user's OS, connected to their telegram (`tele_bot_mcp`).\nCAPABILITIES & TOOLS: You have native access to `duckduckgo_mcp`, `brave-search`, and raw `filesystem` tools for direct file management. You oversee two specialists: `planner_worker` and `coder_worker`.\nGOAL: Automate the user's life, manage files, search the web, and execute programming logic on demand.\nOPERATIONAL RULES:\n1. For quick tasks (web search, reading a file), use your native tools and answer directly.\n2. For multi-step, complex software/logic objectives, forward the context to `planner_worker` to draft a strategy, then pass the strategy to `coder_worker` to implement.\n3. Constantly push updates to the user using Telegram."
        },
        "model": {"provider": "ollama", "model_name": "kimi-k2.5:cloud", "temperature": 0.0},
        "mcp_clients": [
            {"name": "tele_bot_mcp", "transport": "stdio", "command": "uvx", "args": ["agent-telegram-mcp"], "env": {"TELEGRAM_BOT_TOKEN": "your_bot_token"}},
            {"name": "filesystem", "command": "npx.cmd", "args": ["-y", "@modelcontextprotocol/server-filesystem", "./data"]},
            {"name": "duckduckgo_mcp", "command": "npx.cmd", "args": ["-y", "@davidsherret/duckduckgo-search-mcp"]},
            {"name": "brave-search", "command": "npx.cmd", "args": ["-y", "@modelcontextprotocol/server-brave-search"], "env": {"BRAVE_API_KEY": "your_brave_api_key"}}
        ],
        "worker_agents": [
            {
                "name": "planner_worker", 
                "command": "uvx", 
                "args": ["worker-agent"],
                "env": {"WORKER_AGENT_CONFIG": "./service_config/workers/planner_worker.yaml"}
            },
            {
                "name": "coder_worker", 
                "command": "uvx", 
                "args": ["worker-agent"],
                "env": {"WORKER_AGENT_CONFIG": "./service_config/workers/coder_worker.yaml"}
            }
        ],
        "worker_configs": {
            "planner_worker": {
                "agent": {"name": "PlannerWorker", "description": "Breaks down goals into actionable steps."},
                "system_prompt": "IDENTITY: You are the Strategic Planner Worker.\nENVIRONMENT: Execution sandbox. No internet or filesystem access.\nCAPABILITY & TOOLS: Pure cognitive reasoning for breaking down massive goals.\nGOAL: Draft clear, unambiguous, step-by-step pseudo-code or action plans for complex problems.\nOPERATIONAL RULES:\n1. Do not write code.\n2. Analyze the user requested goal.\n3. Break the goal into discrete, testable steps.\n4. Return the plan to the Orchestrator.",
                "model": {"provider": "ollama", "model_name": "kimi-k2.5:cloud", "temperature": 0.0},
                "mcp_clients": []
            },
            "coder_worker": {
                "agent": {"name": "CoderWorker", "description": "Has access to filesystem and shell for code creation."},
                "system_prompt": "IDENTITY: You are a principal software engineer AI.\nENVIRONMENT: You run inside an isolated OS container with strict filesystem access.\nCAPABILITY & TOOLS: You have raw read/write access to the filesystem to manipulate code.\nGOAL: Translate plans and architecture into perfect, production-ready code.\nOPERATIONAL RULES:\n1. Evaluate the plan given to you.\n2. Use the filesystem MCP to read necessary existing code to gain context.\n3. Write the new code using filesystem MCP.\n4. Verify changes are structurally sound. Report success or failure accurately back to the orchestrator.",
                "model": {"provider": "ollama", "model_name": "qwen3-coder:480b-cloud", "temperature": 0.0},
                "mcp_clients": [
                    {"name": "filesystem", "command": "npx.cmd", "args": ["-y", "@modelcontextprotocol/server-filesystem", "./data"]}
                ]
            }
        }
    },
    "security_expert": {
         "agent": {
             "name": "SecurityAuditorAgent",
             "system_prompt": "IDENTITY: You are an Infrastructure Security Auditor orchestrator.\nENVIRONMENT: Isolated control plane for cybersecurity tasks.\nCAPABILITIES & TOOLS: You do NOT have any native tools to prevent exploiting the core layer. You solely delegate to the `scanner_worker`.\nGOAL: Execute safe, structured security audits and penetration tests of designated infrastructure.\nOPERATIONAL RULES:\n1. Intercept auditing instructions.\n2. Validate that the scope is authorized.\n3. Delegate the actual scanning arrays and exploit tests to the `scanner_worker`.\n4. Compile the technical findings of the worker into a human-readable security report."
        },
         "model": {"provider": "ollama", "model_name": "claude-3.5-sonnet", "temperature": 0.0},
         "mcp_clients": [],
         "notify_server": {"enabled": False},
         "worker_agents": [
            {
                "name": "scanner_worker", 
                "command": "uvx", 
                "args": ["worker-agent"],
                "env": {"WORKER_AGENT_CONFIG": "./service_config/workers/scanner_worker.yaml"}
            }
         ],
         "worker_configs": {
             "scanner_worker": {
                 "agent": {"name": "ScannerWorker", "description": "Runs networking scans and generates reports."},
                 "system_prompt": "IDENTITY: You are a Kali Linux Security Scanner Agent.\nENVIRONMENT: Heavily restricted, isolated sandbox that exposes security tools via `kalimcp` and a reporting directory via `filesystem`.\nCAPABILITY & TOOLS: You have access to `kalimcp` (Nmap, Metasploit interfaces, etc.) and `filesystem` scoped to `./sandbox_reports`.\nGOAL: Execute requested network scans, vulnerability probes, and log the findings securely.\nOPERATIONAL RULES: \n1. ONLY scan the target provided.\n2. Execute the commands using Kalimcp.\n3. Write the raw output and your synthesis into a report in the sandbox directory.\n4. AGGRESSIVELY clean up any temporary scan files or packet captures after your report is generated.",
                 "model": {"provider": "ollama", "model_name": "claude-3.5-sonnet", "temperature": 0.0},
                 "mcp_clients": [
                     {"name": "kalimcp", "command": "npx.cmd", "args": ["-y", "kalimcp-server"]},
                     {"name": "filesystem", "command": "npx.cmd", "args": ["-y", "@modelcontextprotocol/server-filesystem", "./sandbox_reports"]}
                 ]
             }
         }
    },
    "coding_agent": {
         "agent": {
             "name": "CodingArchitectAgent",
             "system_prompt": "IDENTITY: You are a Lead Software Architect Orchestrator.\nENVIRONMENT: Engineering environment with access to GitHub and the software life-cycle.\nCAPABILITIES & TOOLS: You have GitHub integration natively via `@modelcontextprotocol/server-github` to manage PRs and issues. You manage the `architect_worker`.\nGOAL: Lead coding migrations, create issues, review pull requests, and manage codebase integrity.\nOPERATIONAL RULES:\n1. Retrieve issue requirements or repository context using the GitHub MCP.\n2. Route complex migrations or refactoring strategies to the `architect_worker`.\n3. Synthesize the architect's output and create Pull Requests or merge code using GitHub MCP."
        },
         "model": {"provider": "ollama", "model_name": "qwen3-coder:480b-cloud", "temperature": 0.0},
         "mcp_clients": [
             {"name": "github", "command": "npx.cmd", "args": ["-y", "@modelcontextprotocol/server-github"], "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "your_github_token"}}
         ],
         "worker_agents": [
            {
                "name": "architect_worker", 
                "command": "uvx", 
                "args": ["worker-agent"],
                "env": {"WORKER_AGENT_CONFIG": "./service_config/workers/architect_worker.yaml"}
            }
         ],
         "worker_configs": {
             "architect_worker": {
                 "agent": {"name": "ArchitectWorker", "description": "Plans codebase migrations."},
                 "system_prompt": "IDENTITY: You are a Staff-Level Software Architect Worker.\nENVIRONMENT: Pure cognitive container without execution tools.\nCAPABILITY & TOOLS: None. You use pure logic and deep pattern recognition of code.\nGOAL: Consume giant blocks of code or feature requests and architect structurally flawless, DRY, and scalable implementations.\nOPERATIONAL RULES:\n1. Outline the architectural changes step-by-step.\n2. Validate edge cases within your logic. \n3. Present the unified design doc back to the Orchestrator for implementation.",
                 "model": {"provider": "ollama", "model_name": "qwen3-coder:480b-cloud", "temperature": 0.0},
                 "mcp_clients": []
             }
         }
    }
}

def load_yaml(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def save_yaml(data: dict, path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

def normalize_model(m_data: dict) -> dict:
    if not isinstance(m_data, dict):
        return {}
    return {
        "provider": m_data.get("provider", "ollama"),
        "model_name": m_data.get("model_name", "kimi-k2.5:cloud"),
        "temperature": m_data.get("temperature", 0.0),
        "base_url": m_data.get("base_url", "http://localhost:11434"),
        "api_key": m_data.get("api_key", "your-api-key-here")
    }

def main():
    parser = argparse.ArgumentParser(description="Create an on-demand agent configuration.")
    parser.add_argument("--profile", required=True, choices=list(PROFILES.keys()) + ["all"], help="Agent profile to generate. Use 'all' for all profiles.")
    parser.add_argument("--output", default="./deployments", help="Output directory for generated configs.")
    args = parser.parse_args()

    profiles_to_run = list(PROFILES.keys()) if args.profile == "all" else [args.profile]
    
    script_dir = Path(__file__).parent
    sample_config_path = script_dir / "sample_config.yaml"

    for profile_name in profiles_to_run:
        profile_data = PROFILES[profile_name]
        
        out_dir = Path(args.output) / profile_name
        out_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. Load base orchestration config
        base_config = load_yaml(str(sample_config_path))

        if not isinstance(base_config, dict):
            base_config = {}

        # 2. Merge orchestrator overrides
        dict_keys = ["agent", "model", "notify_server", "memory", "chat_history", "summarizer"]
        for key in dict_keys:
            if key in profile_data:
                b_conf: dict = base_config
                if key in b_conf and isinstance(b_conf[key], dict):
                    b_conf[key].update(profile_data[key])
                else:
                    b_conf[key] = profile_data[key]
        
        list_keys = ["worker_agents", "mcp_clients"]
        for key in list_keys:
            if key in profile_data:
                base_config[key] = profile_data[key]

        # 3. Save Orchestrator Config
        if "model" in base_config:
            base_config["model"] = normalize_model(base_config["model"])
        if "summarizer" in base_config and "model" in base_config["summarizer"]:
            base_config["summarizer"]["model"] = normalize_model(base_config["summarizer"]["model"])
            
        config_out = out_dir / "config.yaml"
        save_yaml(base_config, str(config_out))

        # 4. Generate Service Yamls
        service_dir = out_dir / "service_config"
        service_dir.mkdir(exist_ok=True)
        
        workers_dir = service_dir / "workers"
        workers_dir.mkdir(exist_ok=True)
        
        sample_notify = script_dir / "service_config" / "sample_notify_config.yaml"
        if sample_notify.exists():
            shutil.copy(sample_notify, service_dir / "notify_config.yaml")
            
        sample_rag = script_dir / "service_config" / "sample_rag_config.yaml"
        if sample_rag.exists():
            shutil.copy(sample_rag, service_dir / "rag_config.yaml")

        # 5. Deploy Isolated Worker Agents Configs
        worker_configs = profile_data.get("worker_configs", {})
        for w_name, w_data in worker_configs.items():
            
            raw_model = w_data.get("model", base_config.get("model", {}))
            normalized_model = normalize_model(raw_model)
            
            # A baseline minimal template for the worker
            worker_yaml = {
                "agent": {"name": w_name, "version": "1.0.0", "description": w_data.get("agent", {}).get("description", "")},
                "system_prompt": w_data.get("system_prompt", "You are a specialist worker agent."),
                "model": normalized_model,
                "mcp_clients": w_data.get("mcp_clients", []),
                "server": {
                    "name": f"{w_name}-server",
                    "port": 8003,
                    "transport": "stdio",
                    "host": "0.0.0.0"
                }
            }
            save_yaml(worker_yaml, str(workers_dir / f"{w_name}.yaml"))

        print(f"✅ Generated '{profile_name}' configuration dynamically.")
        print(f"📁 Output path: {out_dir.resolve()}")
        print(f"🚀 Run it using: python main.py --config \"{config_out.resolve()}\"\n")

if __name__ == "__main__":
    main()
