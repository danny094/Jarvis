// debug.ts - Ultimate WebSocket Debug Server

Deno.serve({ port: 8401, hostname: "0.0.0.0" }, (req) => {
  console.log(`\n[DEBUG] Incoming Request: ${req.method} ${req.url}`);
  
  // Log ALL headers
  console.log("[DEBUG] Headers:");
  for (const [key, value] of req.headers.entries()) {
    console.log(`  ${key}: ${value}`);
  }

  // WebSocket Check
  const upgrade = req.headers.get("upgrade") || "";
  
  if (upgrade.toLowerCase() === "websocket") {
    console.log("[DEBUG] -> WebSocket Upgrade detected! Trying to upgrade...");
    try {
      const { socket, response } = Deno.upgradeWebSocket(req);
      
      socket.onopen = () => console.log("[DEBUG] WS Connected!");
      socket.onmessage = (e) => {
        console.log("[DEBUG] WS Message:", e.data);
        socket.send("Echo: " + e.data);
      };
      socket.onclose = () => console.log("[DEBUG] WS Closed");
      socket.onerror = (e) => console.log("[DEBUG] WS Error:", e);
      
      return response;
    } catch (err) {
      console.error("[DEBUG] !!! Upgrade FAILED:", err);
      return new Response("Upgrade Failed: " + err.message, { status: 500 });
    }
  }

  return new Response("Hello from Deno Debug Server (HTTP works)", { status: 200 });
});

console.log("[DEBUG] Server starting on 0.0.0.0:8401...");
