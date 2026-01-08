import { AgentPreview } from "./agents/AgentPreview";
import { ThemeProvider } from "./core/theme/ThemeProvider";

const App: React.FC = () => {
  // State to store the agent details
  const agentDetails ={
      id: "chatbot",
      object: "chatbot",
      created_at: Date.now(),
      name: "Chatbot",
      description: "This is a sample chatbot.",
      model: "default",
      metadata: {
        logo: "Avatar_Default.svg",
      },
  };

  return (
    <ThemeProvider>
      <div className="app-container">
        <AgentPreview
          resourceId="sample-resource-id"
          agentDetails={agentDetails}
        />
      </div>
    </ThemeProvider>
  );
};

export default App;
