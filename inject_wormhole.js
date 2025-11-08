(function() {
    if (window.__wormhole__) {
        console.log('[Wormhole] Already initialized, skipping');
        return;
    }
    
    const PORT = 8765;
    const ENDPOINT = '/inject';
    
    let ws;
    
    function initWebSocket() {
        ws = new WebSocket(`ws://localhost:${PORT}`);
        
        ws.onopen = () => {
            console.log('[Wormhole] Connected to injection server');
            ws.send(JSON.stringify({ type: 'page_client' }));
        };
        
        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.code) {
                    Promise.resolve(eval(data.code))
                        .then(result => {
                            ws.send(JSON.stringify({ 
                                success: true, 
                                result: result,
                                request_id: data.request_id
                            }));
                        })
                        .catch(error => {
                            ws.send(JSON.stringify({ 
                                success: false, 
                                error: error.message,
                                request_id: data.request_id
                            }));
                        });
                }
            } catch (error) {
                ws.send(JSON.stringify({ 
                    success: false, 
                    error: error.message,
                    request_id: data.request_id
                }));
            }
        };
        
        ws.onerror = (error) => {
            console.error('[Wormhole] WebSocket error:', error);
        };
        
        ws.onclose = () => {
            console.log('[Wormhole] Connection closed, reconnecting...');
            setTimeout(initWebSocket, 2000);
        };
    }
    
    initWebSocket();
    
    window.__wormhole__ = {
        execute: (code) => {
            try {
                return { success: true, result: eval(code) };
            } catch (error) {
                return { success: false, error: error.message };
            }
        },
        status: () => {
            return ws && ws.readyState === WebSocket.OPEN ? 'connected' : 'disconnected';
        }
    };
    
    console.log('[Wormhole] Injection endpoint initialized');
})();
