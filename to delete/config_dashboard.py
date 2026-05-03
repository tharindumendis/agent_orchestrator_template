import streamlit as st
import yaml
from pathlib import Path
import os

# Path to config files
CONFIG_PATH = Path(__file__).parent / "config.yaml"
SERVICE_CONFIG_PATH = Path(__file__).parent / "service_config"

def load_yaml(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        st.error(f"Error loading {file_path}: {e}")
        return None

def save_yaml(file_path, data):
    try:
        with open(file_path, 'w') as f:
            yaml.safe_dump(data, f, default_flow_style=False)
        st.success(f"Saved to {file_path}")
    except Exception as e:
        st.error(f"Error saving {file_path}: {e}")

def main():
    st.title("Agent Head Config Dashboard")

    # Load main config
    config = load_yaml(CONFIG_PATH)
    if not config:
        st.stop()

    # Initialize session state
    if 'config' not in st.session_state:
        st.session_state.config = config
    if 'workers' not in st.session_state:
        st.session_state.workers = config.get('worker_agents', [])
    if 'notify' not in st.session_state:
        st.session_state.notify = config.get('notify', {})
    if 'mcp_clients' not in st.session_state:
        st.session_state.mcp_clients = config.get('mcp_clients', [])

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["Basic Config", "Workers", "Notify Config", "MCP Clients", "Chat Preview", "RAG Config"])

    with tab1:
        st.header("Basic Configuration")

        # Agent section
        st.subheader("Agent Settings")
        col1, col2 = st.columns(2)
        with col1:
            st.session_state.config['agent']['name'] = st.text_input("Agent Name", st.session_state.config['agent'].get('name', ''), key="basic_agent_name")
            st.session_state.config['agent']['version'] = st.text_input("Version", st.session_state.config['agent'].get('version', ''), key="basic_version")
        with col2:
            st.session_state.config['agent']['debug'] = st.checkbox("Debug Mode", st.session_state.config['agent'].get('debug', False), key="basic_debug")
            st.session_state.config['agent']['max_iterations'] = st.number_input("Max Iterations", value=st.session_state.config['agent'].get('max_iterations', 50), key="basic_max_iter")

        st.session_state.config['agent']['description'] = st.text_area("Description", st.session_state.config['agent'].get('description', ''), key="basic_description")
        st.session_state.config['agent']['system_prompt'] = st.text_area("System Prompt", st.session_state.config['agent'].get('system_prompt', ''), height=300, key="basic_system_prompt")

        # Model section
        st.subheader("Model Settings")
        col1, col2 = st.columns(2)
        with col1:
            st.session_state.config['model']['provider'] = st.text_input("Model Provider", st.session_state.config['model'].get('provider', ''), key="basic_provider")
            st.session_state.config['model']['model_name'] = st.text_input("Model Name", st.session_state.config['model'].get('model_name', ''), key="basic_model_name")
            st.session_state.config['model']['base_url'] = st.text_input("Base URL", st.session_state.config['model'].get('base_url', ''), key="basic_base_url")
        with col2:
            st.session_state.config['model']['temperature'] = st.number_input("Temperature", value=st.session_state.config['model'].get('temperature', 0.0), key="basic_temperature")
            st.session_state.config['model']['api_key'] = st.text_input("API Key", st.session_state.config['model'].get('api_key', ''), key="basic_api_key", type="password")

        # Notify Server section
        st.subheader("Notify Server")
        if 'notify_server' not in st.session_state.config:
            st.session_state.config['notify_server'] = {}
        notify_server = st.session_state.config['notify_server']

        notify_server['enabled'] = st.checkbox("Enabled", notify_server.get('enabled', True), key="basic_notify_enabled")
        notify_server['command'] = st.text_input("Command", notify_server.get('command', 'uvx'), key="basic_notify_command")

        # Args
        args = notify_server.get('args', [])
        args_str = ' '.join(args) if isinstance(args, list) else str(args)
        args_input = st.text_input("Args", args_str, key="basic_notify_args")
        notify_server['args'] = args_input.split() if args_input.strip() else []

        # Environment variables
        env_dict = notify_server.get('env', {})
        env_str = '\n'.join([f"{k}={v}" for k, v in env_dict.items()])
        env_input = st.text_area("Environment Variables", env_str, key="basic_notify_env", height=100)
        notify_server['env'] = dict(line.split('=', 1) for line in env_input.split('\n') if '=' in line)

        # Memory section
        st.subheader("Memory Settings")
        if 'memory' not in st.session_state.config:
            st.session_state.config['memory'] = {}
        memory = st.session_state.config['memory']

        col1, col2 = st.columns(2)
        with col1:
            memory['enabled'] = st.checkbox("Enabled", memory.get('enabled', True), key="basic_memory_enabled")
            memory['backend'] = st.selectbox("Backend", ["rag", "sqlite"], index=["rag", "sqlite"].index(memory.get('backend', 'rag')), key="basic_memory_backend")
            memory['memory_dir'] = st.text_input("Memory Directory", memory.get('memory_dir', './memory'), key="basic_memory_dir")
            memory['max_context_entries'] = st.number_input("Max Context Entries", value=memory.get('max_context_entries', 10), key="basic_max_context")
        with col2:
            memory['max_save_length'] = st.number_input("Max Save Length", value=memory.get('max_save_length', 500), key="basic_max_save")
            memory['auto_feed_top_k'] = st.number_input("Auto Feed Top K", value=memory.get('auto_feed_top_k', 3), key="basic_auto_feed_k")
            memory['auto_feed_category'] = st.selectbox("Auto Feed Category", ["all", "recent", "relevant"], index=["all", "recent", "relevant"].index(memory.get('auto_feed_category', 'all')), key="basic_auto_feed_cat")

        # RAG Server subsection
        if 'rag_server' not in memory:
            memory['rag_server'] = {}
        rag_server = memory['rag_server']
        rag_server['command'] = st.text_input("RAG Server Command", rag_server.get('command', 'uvx'), key="basic_rag_command")
        
        # Args for RAG server
        rag_args = rag_server.get('args', [])
        rag_args_str = ' '.join(rag_args) if isinstance(rag_args, list) else str(rag_args)
        rag_args_input = st.text_input("RAG Server Args", rag_args_str, key="basic_rag_args")
        rag_server['args'] = rag_args_input.split() if rag_args_input.strip() else []
        
        rag_server['collection'] = st.text_input("RAG Collection", rag_server.get('collection', 'docs'), key="basic_rag_collection")
        
        # Environment variables for RAG server
        rag_env_dict = rag_server.get('env', {})
        rag_env_str = '\n'.join([f"{k}={v}" for k, v in rag_env_dict.items()])
        rag_env_input = st.text_area("RAG Server Environment", rag_env_str, key="basic_rag_env", height=60)
        rag_server['env'] = dict(line.split('=', 1) for line in rag_env_input.split('\n') if '=' in line)

        # Chat History section
        st.subheader("Chat History")
        if 'chat_history' not in st.session_state.config:
            st.session_state.config['chat_history'] = {}
        chat_history = st.session_state.config['chat_history']
        
        chat_history['backend'] = st.selectbox("Backend", ["sqlite"], index=0 if chat_history.get('backend', 'sqlite') == 'sqlite' else 0, key="basic_chat_backend")
        chat_history['connection_string'] = st.text_input("Connection String", chat_history.get('connection_string', 'sessions.db'), key="basic_chat_conn")

        # Summarizer section
        st.subheader("Summarizer")
        if 'summarizer' not in st.session_state.config:
            st.session_state.config['summarizer'] = {}
        summarizer = st.session_state.config['summarizer']
        
        col1, col2 = st.columns(2)
        with col1:
            summarizer['enabled'] = st.checkbox("Enabled", summarizer.get('enabled', True), key="basic_summarizer_enabled")
            summarizer['summarize_every_n_messages'] = st.number_input("Summarize Every N Messages", value=summarizer.get('summarize_every_n_messages', 2), key="basic_summarize_n")
            summarizer['keep_recent_messages'] = st.number_input("Keep Recent Messages", value=summarizer.get('keep_recent_messages', 4), key="basic_keep_recent")
        with col2:
            summarizer['save_to_memory'] = st.checkbox("Save to Memory", summarizer.get('save_to_memory', True), key="basic_save_to_memory")
            
        # Summarizer model subsection
        if 'model' not in summarizer:
            summarizer['model'] = {}
        sum_model = summarizer['model']
        
        st.write("**Summarizer Model:**")
        col1, col2 = st.columns(2)
        with col1:
            # Use same provider options as main model
            provider_options = ["ollama", "openai", "gemini"]
            current_provider = sum_model.get('provider', st.session_state.config['model'].get('provider', 'ollama'))
            sum_model['provider'] = st.selectbox("Provider", provider_options, 
                                               index=provider_options.index(current_provider) if current_provider in provider_options else 0, 
                                               key="basic_sum_provider")
            sum_model['model_name'] = st.text_input("Model Name", sum_model.get('model_name', ''), key="basic_sum_model")
            sum_model['base_url'] = st.text_input("Base URL", sum_model.get('base_url', ''), key="basic_sum_base_url")
        with col2:
            sum_model['temperature'] = st.number_input("Temperature", value=sum_model.get('temperature', 0.0), key="basic_sum_temp")
            sum_model['api_key'] = st.text_input("API Key", sum_model.get('api_key', ''), key="basic_sum_api_key", type="password")

        if st.button("Save Basic Config"):
            config['agent'] = st.session_state.config['agent']
            config['model'] = st.session_state.config['model']
            config['notify_server'] = st.session_state.config['notify_server']
            config['memory'] = st.session_state.config['memory']
            config['chat_history'] = st.session_state.config['chat_history']
            config['summarizer'] = st.session_state.config['summarizer']
            save_yaml(CONFIG_PATH, config)

    with tab2:
        st.header("Worker Agents")
        for i, worker in enumerate(st.session_state.workers):
            with st.expander(f"Worker {i+1}: {worker.get('name', 'Unnamed')}"):
                worker['name'] = st.text_input(f"Name {i}", worker.get('name', ''), key=f"worker_name_{i}")
                env_dict = worker.get('env', {})
                env_str = '\n'.join([f"{k}={v}" for k, v in env_dict.items()])
                env_input = st.text_area(f"Env {i}", env_str, key=f"worker_env_{i}")
                worker['env'] = dict(line.split('=', 1) for line in env_input.split('\n') if '=' in line)
                
                # Edit worker config file
                config_path = worker.get('env', {}).get('WORKER_AGENT_CONFIG', '')
                if config_path:
                    # Convert relative path to absolute
                    if config_path.startswith('./'):
                        config_file_path = Path(__file__).parent / config_path[2:]
                    else:
                        config_file_path = Path(config_path)
                    
                    if config_file_path.exists():
                        st.subheader(f"Config File: {config_file_path.name}")
                        worker_config = load_yaml(config_file_path)
                        
                        if worker_config:
                            # Agent section
                            if 'agent' not in worker_config:
                                worker_config['agent'] = {}
                            worker_config['agent']['name'] = st.text_input(f"Agent Name {i}", worker_config['agent'].get('name', ''), key=f"worker_agent_name_{i}")
                            worker_config['agent']['version'] = st.text_input(f"Version {i}", worker_config['agent'].get('version', ''), key=f"worker_version_{i}")
                            worker_config['agent']['description'] = st.text_area(f"Description {i}", worker_config['agent'].get('description', ''), key=f"worker_desc_{i}", height=100)
                            
                            # System prompt
                            worker_config['system_prompt'] = st.text_area(f"System Prompt {i}", worker_config.get('system_prompt', ''), key=f"worker_sys_prompt_{i}", height=150)
                            
                            # Model section
                            if 'model' not in worker_config:
                                worker_config['model'] = {}
                            worker_config['model']['provider'] = st.text_input(f"Model Provider {i}", worker_config['model'].get('provider', ''), key=f"worker_provider_{i}")
                            worker_config['model']['model_name'] = st.text_input(f"Model Name {i}", worker_config['model'].get('model_name', ''), key=f"worker_model_{i}")
                            worker_config['model']['temperature'] = st.number_input(f"Temperature {i}", value=worker_config['model'].get('temperature', 0.0), key=f"worker_temp_{i}")
                            worker_config['model']['base_url'] = st.text_input(f"Base URL {i}", worker_config['model'].get('base_url', ''), key=f"worker_url_{i}")
                            
                            # MCP Clients
                            worker_key = f"worker_{i}_mcp"
                            if worker_key not in st.session_state:
                                st.session_state[worker_key] = worker_config.get('mcp_clients', [])
                            
                            st.subheader("MCP Clients")
                            for j, client in enumerate(st.session_state[worker_key]):
                                with st.expander(f"Client {j+1}: {client.get('name', 'Unnamed')}"):
                                    client['name'] = st.text_input(f"Name {j}", client.get('name', ''), key=f"worker_mcp_name_{i}_{j}")
                                    client['transport'] = st.selectbox(f"Transport {j}", ["stdio", "sse"], index=["stdio", "sse"].index(client.get('transport', 'stdio')), key=f"worker_mcp_transport_{i}_{j}")
                                    if client['transport'] == 'stdio':
                                        client['command'] = st.text_input(f"Command {j}", client.get('command', ''), key=f"worker_mcp_command_{i}_{j}")
                                        client['args'] = st.text_area(f"Args {j}", '\n'.join(client.get('args', [])), key=f"worker_mcp_args_{i}_{j}")
                                        env_dict = client.get('env', {})
                                        env_str = '\n'.join([f"{k}={v}" for k, v in env_dict.items()])
                                        env_input = st.text_area(f"Env {j}", env_str, key=f"worker_mcp_env_{i}_{j}")
                                        client['env'] = dict(line.split('=', 1) for line in env_input.split('\n') if '=' in line)
                                    elif client['transport'] == 'sse':
                                        client['url'] = st.text_input(f"URL {j}", client.get('url', ''), key=f"worker_mcp_url_{i}_{j}")
                                        headers_str = yaml.safe_dump(client.get('headers', {}))
                                        headers_input = st.text_area(f"Headers {j}", headers_str, key=f"worker_mcp_headers_{i}_{j}")
                                        client['headers'] = yaml.safe_load(headers_input) if headers_input.strip() else {}
                                    if st.button(f"Delete Client {j+1}", key=f"worker_del_mcp_{i}_{j}"):
                                        st.session_state[worker_key].pop(j)
                                        st.rerun()

                            if st.button("Add MCP Client", key=f"worker_add_mcp_{i}"):
                                st.session_state[worker_key].append({'name': '', 'transport': 'stdio'})
                                st.rerun()

                            worker_config['mcp_clients'] = st.session_state[worker_key]
                            
                            # Save worker config button
                            if st.button(f"Save Config for {worker.get('name', 'Worker')}", key=f"save_worker_config_{i}"):
                                save_yaml(config_file_path, worker_config)
                                st.success(f"Saved {config_file_path.name}")
                        else:
                            st.error(f"Failed to load config file: {config_file_path}")
                    else:
                        st.warning(f"Config file not found: {config_path}")
                
                if st.button(f"Delete Worker {i+1}", key=f"del_worker_{i}"):
                    st.session_state.workers.pop(i)
                    st.rerun()

        # Add new worker with auto-generated config
        st.subheader("Add New Worker")
        col1, col2, col3 = st.columns([2, 3, 1])
        
        with col1:
            new_worker_name = st.text_input("Worker Name", key="new_worker_name")
        with col2:
            new_worker_desc = st.text_input("Worker Description", key="new_worker_desc")
        with col3:
            if st.button("Create Worker", key="create_worker"):
                if new_worker_name:
                    # Ensure workers directory exists
                    workers_dir = SERVICE_CONFIG_PATH / "workers"
                    workers_dir.mkdir(exist_ok=True)
                    
                    # Create config file path
                    config_filename = f"agent_{new_worker_name.lower().replace(' ', '_')}_config.yaml"
                    config_file_path = workers_dir / config_filename
                    
                    # Find next available port (starting from 8001)
                    used_ports = set()
                    for worker in st.session_state.workers:
                        config_path = worker.get('env', {}).get('WORKER_AGENT_CONFIG', '')
                        if config_path:
                            try:
                                worker_config = load_yaml(Path(__file__).parent / config_path[2:])
                                if worker_config and 'server' in worker_config:
                                    used_ports.add(worker_config['server'].get('port', 8000))
                            except:
                                pass
                    
                    next_port = 8001
                    while next_port in used_ports:
                        next_port += 1
                    
                    # Create template config
                    template_config = {
                        'agent': {
                            'name': new_worker_name,
                            'version': '1.0.0',
                            'description': new_worker_desc or f'{new_worker_name} worker agent'
                        },
                        'system_prompt': f'You are {new_worker_name}, a specialized worker agent. Your role is to handle specific tasks as delegated by the orchestrator.',
                        'model': {
                            'provider': 'ollama',
                            'model_name': 'qwen3-coder:480b-cloud',
                            'temperature': 0.2,
                            'base_url': 'http://localhost:11434'
                        },
                        'mcp_clients': [],
                        'server': {
                            'name': f'{new_worker_name}-server',
                            'port': next_port,
                            'transport': 'stdio',
                            'host': '0.0.0.0'
                        }
                    }
                    
                    # Save template config
                    save_yaml(config_file_path, template_config)
                    
                    # Add worker to list
                    new_worker = {
                        'name': new_worker_name,
                        'description': new_worker_desc or f'{new_worker_name} worker agent',
                        'command': 'uvx',
                        'args': ['worker-agent'],
                        'env': {
                            'WORKER_AGENT_CONFIG': f'./service_config/workers/{config_filename}'
                        }
                    }
                    
                    st.session_state.workers.append(new_worker)
                    st.success(f"Created worker '{new_worker_name}' with config file {config_filename}")
                    st.rerun()
                else:
                    st.error("Please enter a worker name")

        if st.button("Save Workers", key="save_workers"):
            config['worker_agents'] = st.session_state.workers
            save_yaml(CONFIG_PATH, config)

    with tab3:
        st.header("Notify Configuration")

        # Load notify config from service_config directory
        notify_config_path = SERVICE_CONFIG_PATH / "notify_config.yaml"
        if notify_config_path.exists():
            notify_config = load_yaml(notify_config_path)

            if notify_config:
                # Basic settings
                st.subheader("Basic Settings")
                notify_config['poll_interval'] = st.number_input("Poll Interval (seconds)", value=notify_config.get('poll_interval', 15), key="notify_poll_interval")
                notify_config['debug'] = st.checkbox("Debug Mode", notify_config.get('debug', True), key="notify_debug")
                notify_config['log_file'] = st.text_input("Log File", notify_config.get('log_file', 'agent_notify.log'), key="notify_log_file")

                # Servers section
                st.subheader("MCP Servers")
                if 'servers' not in notify_config:
                    notify_config['servers'] = []

                servers_key = "notify_servers"
                if servers_key not in st.session_state:
                    st.session_state[servers_key] = notify_config.get('servers', [])

                for i, server in enumerate(st.session_state[servers_key]):
                    with st.expander(f"Server {i+1}: {server.get('name', 'Unnamed')}"):
                        server['name'] = st.text_input(f"Server Name {i}", server.get('name', ''), key=f"notify_server_name_{i}")
                        server['command'] = st.text_input(f"Command {i}", server.get('command', ''), key=f"notify_command_{i}")

                        # Args
                        args = server.get('args', [])
                        args_str = ' '.join(args) if isinstance(args, list) else str(args)
                        args_input = st.text_input(f"Args {i}", args_str, key=f"notify_args_{i}")
                        server['args'] = args_input.split() if args_input.strip() else []

                        # Environment variables
                        env_dict = server.get('env', {})
                        env_str = '\n'.join([f"{k}={v}" for k, v in env_dict.items()])
                        env_input = st.text_area(f"Environment {i}", env_str, key=f"notify_env_{i}", height=100)
                        server['env'] = dict(line.split('=', 1) for line in env_input.split('\n') if '=' in line)

                        # Tools
                        st.write(f"**Tools for {server.get('name', 'Server')}:**")
                        if 'tools' not in server:
                            server['tools'] = []

                        tools_key = f"notify_tools_{i}"
                        if tools_key not in st.session_state:
                            st.session_state[tools_key] = server.get('tools', [])

                        for j, tool in enumerate(st.session_state[tools_key]):
                            with st.container():
                                col1, col2, col3 = st.columns([3, 3, 1])
                                with col1:
                                    tool['tool'] = st.text_input(f"Tool {j}", tool.get('tool', ''), key=f"notify_tool_name_{i}_{j}")
                                with col2:
                                    args_dict = tool.get('args', {})
                                    args_str = yaml.safe_dump(args_dict) if args_dict else ''
                                    args_input = st.text_area(f"Args {j}", args_str.strip(), key=f"notify_tool_args_{i}_{j}", height=60)
                                    try:
                                        tool['args'] = yaml.safe_load(args_input) if args_input.strip() else {}
                                    except yaml.YAMLError:
                                        tool['args'] = {}
                                with col3:
                                    if st.button(f"Del {j}", key=f"notify_del_tool_{i}_{j}"):
                                        st.session_state[tools_key].pop(j)
                                        st.rerun()

                        if st.button(f"Add Tool to {server.get('name', 'Server')}", key=f"notify_add_tool_{i}"):
                            st.session_state[tools_key].append({'tool': '', 'args': {}})
                            st.rerun()

                        server['tools'] = st.session_state[tools_key]

                        if st.button(f"Delete Server {i+1}", key=f"notify_del_server_{i}"):
                            st.session_state[servers_key].pop(i)
                            st.rerun()

                if st.button("Add MCP Server", key="notify_add_server"):
                    st.session_state[servers_key].append({
                        'name': '',
                        'command': 'npx',
                        'args': [],
                        'env': {},
                        'tools': []
                    })
                    st.rerun()

                notify_config['servers'] = st.session_state[servers_key]

                if st.button("Save Notify Config", key="save_notify_config"):
                    save_yaml(notify_config_path, notify_config)
                    st.success("Notify configuration saved!")
            else:
                st.error("Failed to load notify config")
        else:
            st.error(f"Notify config file not found at {notify_config_path}")
            st.info("Create the file manually or ensure Agent_notify is properly set up.")

    with tab4:
        st.header("MCP Clients")
        for i, client in enumerate(st.session_state.mcp_clients):
            with st.expander(f"Client {i+1}: {client.get('name', 'Unnamed')}"):
                client['name'] = st.text_input(f"Name {i}", client.get('name', ''), key=f"mcp_name_{i}")
                client['transport'] = st.selectbox(f"Transport {i}", ["stdio", "sse"], index=["stdio", "sse"].index(client.get('transport', 'stdio')), key=f"mcp_transport_{i}")
                if client['transport'] == 'stdio':
                    client['command'] = st.text_input(f"Command {i}", client.get('command', ''), key=f"mcp_command_{i}")
                    client['args'] = st.text_area(f"Args {i}", '\n'.join(client.get('args', [])), key=f"mcp_args_{i}")
                    env_dict = client.get('env', {})
                    env_str = '\n'.join([f"{k}={v}" for k, v in env_dict.items()])
                    env_input = st.text_area(f"Env {i}", env_str, key=f"mcp_env_{i}")
                    client['env'] = dict(line.split('=', 1) for line in env_input.split('\n') if '=' in line)
                elif client['transport'] == 'sse':
                    client['url'] = st.text_input(f"URL {i}", client.get('url', ''), key=f"mcp_url_{i}")
                    client['headers'] = st.text_area(f"Headers {i}", yaml.safe_dump(client.get('headers', {})), key=f"mcp_headers_{i}")
                if st.button(f"Delete Client {i+1}", key=f"del_mcp_{i}"):
                    st.session_state.mcp_clients.pop(i)
                    st.rerun()

        if st.button("Add MCP Client", key="add_mcp"):
            st.session_state.mcp_clients.append({'name': '', 'transport': 'stdio'})
            st.rerun()

        if st.button("Save MCP Clients", key="save_mcp"):
            config['mcp_clients'] = st.session_state.mcp_clients
            save_yaml(CONFIG_PATH, config)

    with tab5:
        st.header("Chat Preview")
        st.subheader("Current System Prompt")
        st.text_area("System Prompt Preview", st.session_state.config['agent'].get('system_prompt', ''), height=300, disabled=True, key="chat_system_prompt")
        st.write("Chat functionality placeholder - system prompt loaded above")

    with tab6:
        st.header("RAG Configuration")
        
        # Load RAG config
        rag_config_path = Path(__file__).parent.parent / "Agent_rag" / "config.yaml"
        if rag_config_path.exists():
            rag_config = load_yaml(rag_config_path)
            
            if rag_config:
                # Server section
                st.subheader("Server")
                if 'server' not in rag_config:
                    rag_config['server'] = {}
                rag_config['server']['name'] = st.text_input("Server Name", rag_config['server'].get('name', ''), key="rag_server_name")
                rag_config['server']['transport'] = st.selectbox("Transport", ["stdio", "sse"], index=["stdio", "sse"].index(rag_config['server'].get('transport', 'stdio')), key="rag_transport")
                rag_config['server']['port'] = st.number_input("Port", value=rag_config['server'].get('port', 8002), key="rag_port")
                rag_config['server']['host'] = st.text_input("Host", rag_config['server'].get('host', '0.0.0.0'), key="rag_host")
                
                # Embeddings section
                st.subheader("Embeddings")
                if 'embeddings' not in rag_config:
                    rag_config['embeddings'] = {}
                rag_config['embeddings']['provider'] = st.selectbox("Provider", ["ollama", "onnx"], index=["ollama", "onnx"].index(rag_config['embeddings'].get('provider', 'ollama')), key="rag_emb_provider")
                
                if rag_config['embeddings']['provider'] == 'onnx':
                    rag_config['embeddings']['model'] = st.text_input("Model", rag_config['embeddings'].get('model', 'all-MiniLM-L6-v2'), key="rag_onnx_model")
                    rag_config['embeddings']['device'] = st.selectbox("Device", ["cpu", "cuda"], index=["cpu", "cuda"].index(rag_config['embeddings'].get('device', 'cpu')), key="rag_device")
                else:  # ollama
                    rag_config['embeddings']['ollama_base_url'] = st.text_input("Ollama Base URL", rag_config['embeddings'].get('ollama_base_url', 'http://localhost:11434'), key="rag_ollama_url")
                    rag_config['embeddings']['ollama_model'] = st.text_input("Ollama Model", rag_config['embeddings'].get('ollama_model', 'nomic-embed-text'), key="rag_ollama_model")
                
                # Store section
                st.subheader("Store")
                if 'store' not in rag_config:
                    rag_config['store'] = {}
                rag_config['store']['persist_dir'] = st.text_input("Persist Directory", rag_config['store'].get('persist_dir', './chroma_db'), key="rag_persist_dir")
                rag_config['store']['default_collection'] = st.text_input("Default Collection", rag_config['store'].get('default_collection', 'default'), key="rag_collection")
                
                # Chunking section
                st.subheader("Chunking")
                if 'chunking' not in rag_config:
                    rag_config['chunking'] = {}
                rag_config['chunking']['chunk_size'] = st.number_input("Chunk Size", value=rag_config['chunking'].get('chunk_size', 500), key="rag_chunk_size")
                rag_config['chunking']['chunk_overlap'] = st.number_input("Chunk Overlap", value=rag_config['chunking'].get('chunk_overlap', 50), key="rag_chunk_overlap")
                
                # Watch section
                st.subheader("Watch")
                if 'watch' not in rag_config:
                    rag_config['watch'] = {}
                rag_config['watch']['enabled'] = st.checkbox("Enabled", rag_config['watch'].get('enabled', True), key="rag_watch_enabled")
                watch_dirs = rag_config['watch'].get('directories', [])
                watch_dirs_str = '\n'.join(watch_dirs)
                watch_dirs_input = st.text_area("Watch Directories", watch_dirs_str, key="rag_watch_dirs")
                rag_config['watch']['directories'] = [d.strip() for d in watch_dirs_input.split('\n') if d.strip()]
                
                # Logging section
                st.subheader("Logging")
                if 'logging' not in rag_config:
                    rag_config['logging'] = {}
                rag_config['logging']['level'] = st.selectbox("Level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], 
                                                            index=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"].index(rag_config['logging'].get('level', 'INFO')), key="rag_log_level")
                rag_config['logging']['file_path'] = st.text_input("Log File Path", rag_config['logging'].get('file_path', './logs/rag_server.log'), key="rag_log_file")
                rag_config['logging']['max_file_size'] = st.number_input("Max File Size (bytes)", value=rag_config['logging'].get('max_file_size', 10485760), key="rag_max_size")
                rag_config['logging']['backup_count'] = st.number_input("Backup Count", value=rag_config['logging'].get('backup_count', 5), key="rag_backup_count")
                
                if st.button("Save RAG Config", key="save_rag"):
                    save_yaml(rag_config_path, rag_config)
                    st.success("RAG configuration saved!")
            else:
                st.error("Failed to load RAG config")
        else:
            st.error(f"RAG config file not found at {rag_config_path}")

if __name__ == "__main__":
    main()