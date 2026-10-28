//! The browser's end of an OGP link: iroh compiled to WebAssembly, as thin
//! as it can be. It dials an OGP by its ID over n0's relays (a browser can't
//! send UDP, so it never goes direct), moves datagrams and takes the streams
//! the other side opens. What they say is the page's business:
//! docs/assets/remote.js speaks the Friends protocol.

use iroh::{
    Endpoint, EndpointId, SecretKey,
    endpoint::{Connection, VarInt, presets},
};
use js_sys::{Promise, Uint8Array};
use wasm_bindgen::prelude::*;
use wasm_bindgen_futures::future_to_promise;

#[wasm_bindgen(start)]
fn start() {
    console_error_panic_hook::set_once();
}

fn js_err(e: impl std::fmt::Display) -> JsValue {
    JsError::new(&e.to_string()).into()
}

/// This browser's endpoint.
#[wasm_bindgen]
pub struct Guest {
    ep: Endpoint,
}

#[wasm_bindgen]
impl Guest {
    /// Bind an endpoint with `key`, the 32-byte secret the page keeps, so
    /// this browser is the same friend next time.
    pub async fn spawn(key: Vec<u8>) -> Result<Guest, JsError> {
        let bytes: [u8; 32] = key
            .as_slice()
            .try_into()
            .map_err(|_| JsError::new("the key must be 32 bytes"))?;
        let ep = Endpoint::builder(presets::N0)
            .secret_key(SecretKey::from_bytes(&bytes))
            .bind()
            .await
            .map_err(|e| JsError::new(&e.to_string()))?;
        Ok(Guest { ep })
    }

    pub fn id(&self) -> String {
        self.ep.id().to_string()
    }

    /// Dial `peer` (64 hex digits) for `alpn`; resolves to a `Link`.
    pub fn connect(&self, peer: String, alpn: String) -> Promise {
        let ep = self.ep.clone();
        future_to_promise(async move {
            let id: EndpointId = peer.parse().map_err(js_err)?;
            let conn = ep.connect(id, alpn.as_bytes()).await.map_err(js_err)?;
            Ok(JsValue::from(Link { conn }))
        })
    }

    pub fn close(&self) -> Promise {
        let ep = self.ep.clone();
        future_to_promise(async move {
            ep.close().await;
            Ok(JsValue::UNDEFINED)
        })
    }
}

/// One connection: datagrams in and out.
#[wasm_bindgen]
pub struct Link {
    conn: Connection,
}

#[wasm_bindgen]
impl Link {
    pub fn send(&self, data: &[u8]) -> Result<(), JsError> {
        self.conn
            .send_datagram(bytes::Bytes::copy_from_slice(data))
            .map_err(|e| JsError::new(&e.to_string()))
    }

    /// The next datagram; rejects once the connection is gone (the error
    /// carries the other side's reason).
    pub fn recv(&self) -> Promise {
        let conn = self.conn.clone();
        future_to_promise(async move {
            let data = conn.read_datagram().await.map_err(js_err)?;
            Ok(Uint8Array::from(&data[..]).into())
        })
    }

    /// The next stream the other side opens, read whole (at most `max`
    /// bytes) -- an avatar board is too big for a datagram.
    pub fn recv_stream(&self, max: u32) -> Promise {
        let conn = self.conn.clone();
        future_to_promise(async move {
            let mut recv = conn.accept_uni().await.map_err(js_err)?;
            let data = recv.read_to_end(max as usize).await.map_err(js_err)?;
            Ok(Uint8Array::from(&data[..]).into())
        })
    }

    pub fn close(&self, code: u32, reason: String) {
        self.conn.close(VarInt::from_u32(code), reason.as_bytes());
    }
}
