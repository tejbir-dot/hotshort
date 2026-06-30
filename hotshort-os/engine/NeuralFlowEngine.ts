import eventBus from "./EventBus";
import reactorEngine from "./ReactorEngine";
import packetScheduler from "./PacketScheduler";

class NeuralFlowEngine {
  constructor() {
    this.register();
  }

  private register() {
    eventBus.on(
      "WHISPER_STARTED",
      this.whisperStarted
    );

    eventBus.on(
      "TRANSCRIPT_READY",
      this.transcriptReady
    );

    eventBus.on(
      "HOOK_DETECTED",
      this.hookDetected
    );

    eventBus.on(
      "RANKING_UPDATED",
      this.rankingUpdated
    );

    eventBus.on(
      "EDITOR_STARTED",
      this.editorStarted
    );

    eventBus.on(
      "RENDER_STARTED",
      this.renderStarted
    );

    eventBus.on(
      "RENDER_FINISHED",
      this.renderFinished
    );
  }

  private whisperStarted = () => {
    reactorEngine.setThinking(true);
    reactorEngine.setEnergy(.55);
    reactorEngine.pulse(.45);

    packetScheduler.send(
      "Core",
      "Whisper",
      {
        color: "#59B7FF",
      }
    );
  };

  private transcriptReady = () => {
    reactorEngine.setEnergy(.65);
    reactorEngine.pulse(.55);

    packetScheduler.send(
      "Whisper",
      "Semantic",
      {
        color: "#FFFFFF",
      }
    );
  };

  private hookDetected = () => {
    reactorEngine.setEnergy(.95);
    reactorEngine.setTemperature(.9);
    reactorEngine.pulse(1);

    packetScheduler.send(
      "Semantic",
      "Hook",
      {
        color: "#FFE08A",
      }
    );
  };

  private rankingUpdated = () => {
    packetScheduler.send(
      "Hook",
      "Ranking",
      {
        color: "#FFD76E",
      }
    );
  };

  private editorStarted = () => {
    packetScheduler.send(
      "Ranking",
      "Editor",
      {
        color: "#F6C453",
      }
    );

    reactorEngine.pulse(.7);
  };

  private renderStarted = () => {
    packetScheduler.send(
      "Editor",
      "Renderer",
      {
        color: "#FFE08A",
      }
    );

    reactorEngine.setEnergy(1);

    reactorEngine.pulse(1);
  };

  private renderFinished = () => {
    reactorEngine.setThinking(false);

    reactorEngine.setEnergy(.45);

    reactorEngine.setTemperature(.25);

    reactorEngine.pulse(.35);

    packetScheduler.send(
      "Renderer",
      "Core",
      {
        color: "#FFFFFF",
      }
    );
  };
}

const neuralFlowEngine = new NeuralFlowEngine();

export default neuralFlowEngine;