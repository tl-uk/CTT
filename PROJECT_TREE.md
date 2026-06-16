# CTT Project Structure

**Generated:** Tue Jun 16 08:25:57 BST 2026

```
└── CTT
    ├── .env
    ├── ARCHITECTURE.md
    ├── Makefile
    ├── PROJECT_TREE.md
    ├── api
    │   └── proto
    │       └── ctt_messages.proto
    ├── deploy
    │   ├── docker-compose-redpanda.yml
    │   ├── docker-compose.domain-dhl.yml
    │   ├── docker-compose.yml
    │   └── grafana
    │       ├── dashboards
    │       │   └── ctt-dashboard.json
    │       └── datasources
    │           └── ctt-api.yaml
    ├── scripts
    │   ├── diag_bat_key.py
    │   ├── generate_domain_compose.py
    │   ├── generate_project_tree.py
    │   ├── monitor_pipeline.py
    │   ├── observe_pipeline.py
    │   ├── test_bat_api.py
    │   ├── test_bat_bus.py
    │   ├── test_e2e.py
    │   ├── test_multi_domain.py
    │   ├── test_py_cpp_bridge.py
    │   └── test_sme_feed.py
    └── services
        ├── config
        │   ├── belief_envelope_schema.json
        │   ├── domains.yaml
        │   ├── ports.py
        │   ├── self_descriptions_registry.yaml
        │   ├── settings.py
        │   └── validate_ports.py
        ├── data-pipeline
        │   ├── fusion
        │   │   ├── Dockerfile
        │   │   ├── __init__.py
        │   │   ├── ctt_messages_pb2.py
        │   │   └── fusion_engine.py
        │   ├── ingestor
        │   │   ├── Dockerfile
        │   │   ├── configs
        │   │   │   └── dft_traffic_flow_ingestor_config.yaml
        │   │   ├── gtfs_harvester.py
        │   │   ├── gtfs_loader.py
        │   │   ├── harvester.py
        │   │   ├── harvester_mock.py
        │   │   ├── main.py
        │   │   └── tests
        │   │       └── fixtures
        │   │           └── dft_traffic_flow_mock_payload.json
        │   └── interpreter
        │       ├── Dockerfile
        │       └── semantic_agent.py
        ├── l1-engine
        │   ├── CMakeLists.txt
        │   ├── Dockerfile
        │   ├── include
        │   │   ├── AgentComponents.h
        │   │   ├── DataBridge.h
        │   │   ├── PortConfig.h
        │   │   └── SimulationEngine.h
        │   └── src
        │       ├── DataBridge.cpp
        │       ├── SimulationEngine.cpp
        │       └── main.cpp
        ├── l2-bridge
        │   ├── Dockerfile
        │   ├── dashboard.py
        │   └── requirements.txt
        ├── l2-orchestrator
        │   ├── Dockerfile
        │   ├── README.md
        │   ├── orchestrator.py
        │   └── requirements.txt
        ├── l3-analytics
        │   └── requirements.txt
        ├── l4-spatial
        │   └── README.md
        ├── l5-macro
        │   ├── Dockerfile
        │   ├── __init__.py
        │   ├── audit_logger.py
        │   ├── federation_bridge.py
        │   └── requirements.txt
        ├── l6-gaiax
        │   ├── Dockerfile
        │   ├── README.md
        │   ├── edc-deployment.yaml
        │   ├── edc_gateway.py
        │   ├── policy_enforcer.py
        │   ├── requirements.txt
        │   ├── self-descriptions
        │   │   └── gaiax_self_description_dhl_express.json
        │   └── self_description.json
        └── l7-kg
            ├── README.md
            ├── include
            │   └── ssn_experience_component.h
            ├── kg_bridge.py
            ├── learn_mod.py
            ├── requirements.txt
            └── sig_compressor.py
```