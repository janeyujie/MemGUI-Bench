// MemGUI-Bench Configuration
// Agent list is loaded from data/agents/index.json

let AGENT_FILES = [];

// Task counts (fixed for MemGUI-Bench)
const TASK_COUNTS = {
  total: 128,
  difficulty: {
    easy: 48,
    medium: 42,
    hard: 38
  },
  crossApp: {
    app1: 28,
    app2: 56,
    app3: 34,
    app4: 10
  }
};

// Load agent list from data/index.json
async function loadAgentList() {
  try {
    const response = await fetch('data/index.json');
    if (response.ok) {
      const data = await response.json();
      AGENT_FILES = data.agents || [];
    }
  } catch (error) {
    console.error('Failed to load agent list:', error);
  }
  return AGENT_FILES;
}
