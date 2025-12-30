## Issue tracker

- Unify topology.nodes and Simulator.nodes.
- The BlockProducer should just be a timer that selects an honest node and sends a PRODUCE_BLOCK event to it. Blob selection and block announcement logic should be inside the honest.py.
