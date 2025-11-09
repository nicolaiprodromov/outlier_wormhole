(function () {
  if (window.__wormhole__) {
    console.log("[Wormhole] Already initialized, skipping");
    return;
  }

  const PORT = 8766;
  let ws;

  const commandHandlers = {
    createConversation: async (params) => {
      const { prompt, model, systemMessage } = params;
      const baseUrl = "https://app.outlier.ai/internal/experts/assistant";

      const csrfMatch = document.cookie.match(/_csrf=([^;]+)/);
      const csrfToken = csrfMatch ? decodeURIComponent(csrfMatch[1]) : "";

      const createResponse = await fetch(baseUrl + "/conversations", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        credentials: "include",
        body: JSON.stringify({
          prompt: { text: prompt, images: [] },
          model: model,
        }),
      });

      if (!createResponse.ok) {
        throw new Error(
          "Failed to create conversation: " + createResponse.status,
        );
      }

      const conversation = await createResponse.json();

      const messageResponse = await fetch(
        baseUrl + "/conversations/" + conversation.id + "/turn-streaming",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken,
            accept: "text/event-stream",
          },
          credentials: "include",
          body: JSON.stringify({
            prompt: {
              model: model,
              text: prompt,
              images: [],
              systemMessage: systemMessage,
              modelWasSwitched: false,
            },
            model: model,
            systemMessage: systemMessage,
            parentIdx: 0,
          }),
        },
      );

      if (!messageResponse.ok) {
        throw new Error("Failed to send message: " + messageResponse.status);
      }

      const reader = messageResponse.body.getReader();
      const decoder = new TextDecoder();
      let fullResponse = "";

      while (true) {
        const result = await reader.read();
        if (result.done) break;

        const chunk = decoder.decode(result.value);
        const lines = chunk.split("\n");

        for (const line of lines) {
          if (line.startsWith("data: ") && !line.includes("[DONE]")) {
            const data = line.slice(6);
            try {
              const parsed = JSON.parse(data);
              if (parsed.choices?.[0]?.delta?.content) {
                fullResponse += parsed.choices[0].delta.content;
              }
            } catch (e) {}
          }
        }
      }

      return {
        success: true,
        conversationId: conversation.id,
        response: fullResponse,
      };
    },

    sendMessage: async (params) => {
      const { conversationId, prompt, model, systemMessage } = params;
      const baseUrl = "https://app.outlier.ai/internal/experts/assistant";

      const csrfMatch = document.cookie.match(/_csrf=([^;]+)/);
      const csrfToken = csrfMatch ? decodeURIComponent(csrfMatch[1]) : "";

      const messageResponse = await fetch(
        baseUrl + "/conversations/" + conversationId + "/turn-streaming",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken,
            accept: "text/event-stream",
          },
          credentials: "include",
          body: JSON.stringify({
            prompt: {
              model: model,
              text: prompt,
              images: [],
              systemMessage: systemMessage,
              modelWasSwitched: false,
            },
            model: model,
            systemMessage: systemMessage,
            parentIdx: 0,
          }),
        },
      );

      if (!messageResponse.ok) {
        throw new Error("Failed to send message: " + messageResponse.status);
      }

      const reader = messageResponse.body.getReader();
      const decoder = new TextDecoder();
      let fullResponse = "";

      while (true) {
        const result = await reader.read();
        if (result.done) break;

        const chunk = decoder.decode(result.value);
        const lines = chunk.split("\n");

        for (const line of lines) {
          if (line.startsWith("data: ") && !line.includes("[DONE]")) {
            const data = line.slice(6);
            try {
              const parsed = JSON.parse(data);
              if (parsed.choices?.[0]?.delta?.content) {
                fullResponse += parsed.choices[0].delta.content;
              }
            } catch (e) {}
          }
        }
      }

      return { success: true, response: fullResponse };
    },
  };

  function initWebSocket() {
    ws = new WebSocket(`ws://localhost:${PORT}`);

    ws.onopen = () => {
      console.log("[Wormhole] Connected to injection server");
      ws.send(JSON.stringify({ type: "page_client" }));
    };

    ws.onmessage = async (event) => {
      let message;
      try {
        message = JSON.parse(event.data);

        if (message.command && commandHandlers[message.command]) {
          try {
            const result = await commandHandlers[message.command](
              message.params || {},
            );
            ws.send(
              JSON.stringify({
                success: true,
                result: result,
                request_id: message.request_id,
              }),
            );
          } catch (error) {
            ws.send(
              JSON.stringify({
                success: false,
                error: error.message,
                request_id: message.request_id,
              }),
            );
          }
        } else {
          ws.send(
            JSON.stringify({
              success: false,
              error: "Unknown command: " + message.command,
              request_id: message.request_id,
            }),
          );
        }
      } catch (error) {
        console.error("[Wormhole] Error processing message:", error.message);
        try {
          ws.send(
            JSON.stringify({
              success: false,
              error: error.message,
              request_id: message?.request_id,
            }),
          );
        } catch (e) {
          console.error("[Wormhole] Failed to send error response:", e);
        }
      }
    };

    ws.onerror = (error) => {
      console.error("[Wormhole] WebSocket error:", error);
    };

    ws.onclose = () => {
      console.log("[Wormhole] Connection closed, reconnecting...");
      setTimeout(initWebSocket, 2000);
    };
  }

  initWebSocket();

  window.__wormhole__ = {
    status: () => {
      return ws && ws.readyState === WebSocket.OPEN
        ? "connected"
        : "disconnected";
    },
    commands: Object.keys(commandHandlers),
  };

  console.log("[Wormhole] Injection endpoint initialized");
})();
