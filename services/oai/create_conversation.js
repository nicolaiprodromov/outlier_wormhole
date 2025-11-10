(async function () {
  const input = INPUT_DATA;
  const promptText = input.prompt || "Hello";
  const model = input.model || "claude-sonnet-4-5-20250929";
  const systemMessage =
    input.systemMessage || "You are a helpful chat assistant.";

  const baseUrl = "https://app.outlier.ai/internal/experts/assistant";

  const csrfMatch = document.cookie.match(/_csrf=([^;]+)/);
  const csrfToken = csrfMatch ? decodeURIComponent(csrfMatch[1]) : "";

  try {
    const createResponse = await fetch(baseUrl + "/conversations", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
      },
      credentials: "include",
      body: JSON.stringify({
        prompt: {
          text: promptText,
          images: [],
        },
        model: model,
      }),
    });

    if (!createResponse.ok) {
      throw new Error(
        "Failed to create conversation: " + createResponse.status,
      );
    }

    const conversation = await createResponse.json();

    const combinedPrompt = systemMessage + "\n\n" + promptText;
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
            text: combinedPrompt,
            images: [],
            systemMessage: "",
            modelWasSwitched: false,
          },
          model: model,
          systemMessage: "",
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
            if (
              parsed.choices &&
              parsed.choices[0] &&
              parsed.choices[0].delta &&
              parsed.choices[0].delta.content
            ) {
              const content = parsed.choices[0].delta.content;
              fullResponse += content;
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
  } catch (error) {
    return { success: false, error: error.message };
  }
})();
