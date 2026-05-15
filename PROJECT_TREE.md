# CTT Project Structure

**Generated:** Fri May 15 17:12:57 BST 2026

```
└── CTT
    ├── Makefile
    ├── api
    │   └── proto
    │       └── ctt_messages.proto
    ├── scripts
    │   ├── generate_project_tree.py
    │   ├── test_py_cpp_bridge.py
    │   └── test_sme_feed.py
    └── services
        ├── data-pipeline
        │   ├── fusion
        │   │   ├── __init__.py
        │   │   ├── ctt_messages_pb2.py
        │   │   └── fusion_engine.py
        │   ├── ingestor
        │   │   ├── harvester.py
        │   │   └── main.py
        │   └── interpreter
        │       └── semantic_agent.py
        ├── l1-engine
        │   ├── CMakeLists.txt
        │   ├── include
        │   │   ├── AgentComponents.hpp
        │   │   ├── DataBridge.hpp
        │   │   └── SimulationEngine.hpp
        │   └── src
        │       ├── DataBridge.cpp
        │       ├── SimulationEngine.cpp
        │       └── main.cpp
        └── l2-bridge
            ├── dashboard.py
            └── requirements.txt
```