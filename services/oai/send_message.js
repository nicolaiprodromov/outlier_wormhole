(async function () {
  const input = INPUT_DATA;
  const conversationId = input.conversationId;
  const promptText = input.prompt;
  const model = input.model || "claude-sonnet-4-5-20250929";
  const systemMessage =
    input.systemMessage || "You are a helpful chat assistant.";
  const parentIdx = input.parentIdx || 0;
  const baseUrl = "https://app.outlier.ai/internal/experts/assistant";
  const csrfMatch = document.cookie.match(/_csrf=([^;]+)/);
  const csrfToken = csrfMatch ? decodeURIComponent(csrfMatch[1]) : "";
  try {
    const combinedPrompt = systemMessage + "\n\n" + promptText;
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
            text: combinedPrompt,
            images: [],
            systemMessage: "",
            modelWasSwitched: false,
          },
          model: model,
          systemMessage: "",
          parentIdx: parentIdx,
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
      conversationId: conversationId,
      response: fullResponse,
    };
  } catch (error) {
    return { success: false, error: error.message };
  }
})();
