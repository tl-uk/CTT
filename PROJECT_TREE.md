# CTT Project Structure

**Generated:** Mon May 18 22:33:32 BST 2026

```
└── CTT
    ├── .env
    ├── Makefile
    ├── PROJECT_TREE.md
    ├── api
    │   └── proto
    │       └── ctt_messages.proto
    ├── docker-compose.yml
    ├── scripts
    │   ├── diag_bat_key.py
    │   ├── generate_project_tree.py
    │   ├── monitor_pipeline.py
    │   ├── observe_pipeline.py
    │   ├── test_bat_api.py
    │   ├── test_bat_bus.py
    │   ├── test_e2e.py
    │   ├── test_py_cpp_bridge.py
    │   └── test_sme_feed.py
    └── services
        ├── config
        │   ├── ports.py
        │   ├── settings.py
        │   └── validate_ports.py
        ├── data-pipeline
        │   ├── fusion
        │   │   ├── __init__.py
        │   │   ├── ctt_messages_pb2.py
        │   │   └── fusion_engine.py
        │   ├── ingestor
        │   │   ├── gtfs_harvester.py
        │   │   ├── gtfs_loader.py
        │   │   ├── harvester.py
        │   │   ├── harvester_mock.py
        │   │   └── main.py
        │   └── interpreter
        │       └── semantic_agent.py
        ├── l1-engine
        │   ├── CMakeLists.txt
        │   ├── include
        │   │   ├── AgentComponents.h
        │   │   ├── DataBridge.h
        │   │   ├── PortConfig.h
        │   │   └── SimulationEngine.h
        │   └── src
        │       ├── DataBridge.cpp
        │       ├── SimulationEngine.cpp
        │       └── main.cpp
        └── l2-bridge
            ├── dashboard.py
            └── requirements.txt
```