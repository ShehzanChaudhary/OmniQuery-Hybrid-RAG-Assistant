// Relative URLs — the API is served from the same origin as this page
// (FastAPI serves both), so this works unchanged in dev, Docker, and Azure.
const API_URL = "/query";
const STREAM_API_URL = "/query/stream";
const SESSIONS_API_URL = "/sessions";
const DOCUMENTS_API_URL = "/documents";
const TABLES_API_URL = "/tables";

const chatBox = document.querySelector(".chat-inner");
const questionInput = document.getElementById("question");
const sendButton = document.getElementById("send-btn");
const sessionsList = document.getElementById("sessions-list");
const newChatBtn = document.getElementById("new-chat-btn");

const chatBoxContainer = document.getElementById("chat-box");
const inputArea = document.getElementById("input-area");
const headerTitle = document.getElementById("header-title");
const documentsBtn = document.getElementById("documents-btn");
const documentsView = document.getElementById("documents-view");
const documentsList = document.getElementById("documents-list");
const pdfUploadInput = document.getElementById("pdf-upload-input");
const uploadStatusEl = document.getElementById("upload-status");
const micButton = document.getElementById("mic-btn");

const authView = document.getElementById("auth-view");
const mainApp = document.getElementById("main-app");
const authForm = document.getElementById("auth-form");
const authEmail = document.getElementById("auth-email");
const authPassword = document.getElementById("auth-password");
const authSubmitBtn = document.getElementById("auth-submit-btn");
const authError = document.getElementById("auth-error");
const authSubtitle = document.getElementById("auth-subtitle");
const authToggleText = document.getElementById("auth-toggle-text");
const authToggleLink = document.getElementById("auth-toggle-link");
const logoutBtn = document.getElementById("logout-btn");

const AUTH_LOGIN_URL = "/auth/login";
const AUTH_SIGNUP_URL = "/auth/signup";

let authMode = "login";   // "login" | "signup"

let currentSessionId = null;
let isStreaming = false;

marked.setOptions({ breaks: true });

// Markdown (and DOMPurify) don't know about LaTeX and will mangle things like
// \text{Sublayer} (underscores/braces get read as markdown syntax). So math
// segments are pulled out before markdown parsing and spliced back in after,
// then KaTeX typesets them from the live DOM.
function extractMath(text) {
    const store = [];
    const stash = (raw) => `@@MATH${store.push(raw) - 1}@@`;

    text = text.replace(/\$\$([\s\S]+?)\$\$/g, (_, expr) => stash(`$$${expr}$$`));
    text = text.replace(/\\\[([\s\S]+?)\\\]/g, (_, expr) => stash(`\\[${expr}\\]`));
    text = text.replace(/\\\(([\s\S]+?)\\\)/g, (_, expr) => stash(`\\(${expr}\\)`));
    text = text.replace(/\$([^\$\n]+?)\$/g, (_, expr) => stash(`$${expr}$`));

    return { text, store };
}

function escapeHtml(text) {
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function restoreMath(html, store) {
    return html.replace(/@@MATH(\d+)@@/g, (_, i) => escapeHtml(store[Number(i)]));
}

function renderMarkdown(text) {
    const { text: withPlaceholders, store } = extractMath(text);
    const html = DOMPurify.sanitize(marked.parse(withPlaceholders));
    return restoreMath(html, store);
}

function typesetMath(el) {
    if (window.renderMathInElement) {
        renderMathInElement(el, {
            delimiters: [
                { left: "$$", right: "$$", display: true },
                { left: "\\[", right: "\\]", display: true },
                { left: "\\(", right: "\\)", display: false },
                { left: "$", right: "$", display: false },
            ],
            throwOnError: false,
        });
    }
}

function setRenderedContent(el, text) {
    el.innerHTML = renderMarkdown(text);
    typesetMath(el);
}

function timeAgo() {
    return "just now";
}

// The backend appends "\n\n**Sources:** file.pdf (Page 3, Page 5); other.xlsx (Page 2)"
// straight onto the answer text. Pull that off so it can be rendered as citation
// cards instead of a plain bold-text line inside the message.
function extractCitations(text) {
    const match = text.match(/\n\n\*\*Sources:\*\*\s*([\s\S]+)$/);
    if (!match) {
        return { text, citations: [] };
    }

    const cleanText = text.slice(0, match.index);
    const citations = match[1]
        .split(";")
        .map(part => part.trim())
        .filter(Boolean)
        .map(part => {
            const pageMatch = part.match(/^(.*?)\s*\(([^)]*)\)\s*$/);
            if (!pageMatch) {
                return { filename: part, pages: [] };
            }
            const pages = pageMatch[2]
                .split(",")
                .map(p => p.trim())
                .filter(Boolean);
            return { filename: pageMatch[1].trim(), pages };
        });

    return { text: cleanText, citations };
}

function renderCitations(container, citations) {
    if (!citations || citations.length === 0) return;

    const wrap = document.createElement("div");
    wrap.className = "citations";

    const label = document.createElement("div");
    label.className = "citations-label";
    label.textContent = citations.length === 1 ? "1 Source" : `${citations.length} Sources`;
    wrap.appendChild(label);

    const list = document.createElement("div");
    list.className = "citations-list";

    citations.forEach((citation, index) => {
        const card = document.createElement("div");
        card.className = "citation-card";

        const badge = document.createElement("span");
        badge.className = "citation-index";
        badge.textContent = index + 1;
        card.appendChild(badge);

        const name = document.createElement("span");
        name.className = "citation-name";
        name.textContent = citation.filename;
        card.appendChild(name);

        if (citation.pages.length > 0) {
            const tooltip = document.createElement("span");
            tooltip.className = "citation-tooltip";
            tooltip.textContent = citation.pages.join(" · ");
            card.appendChild(tooltip);
        }

        list.appendChild(card);
    });

    wrap.appendChild(list);
    container.appendChild(wrap);
}

function renderMeta(container, { time_taken, tokens_used } = {}) {
    if (time_taken === undefined && tokens_used === undefined) return;

    const meta = document.createElement("div");
    meta.className = "meta-info";
    if (time_taken !== undefined) meta.innerHTML += `<span>${time_taken}s</span>`;
    if (tokens_used !== undefined) meta.innerHTML += `<span>${tokens_used} tokens</span>`;
    container.appendChild(meta);
}

function renderMessageActions(container, textToCopy) {
    const actions = document.createElement("div");
    actions.className = "message-actions";

    const copyBtn = document.createElement("button");
    copyBtn.title = "Copy";
    copyBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`;
    copyBtn.addEventListener("click", () => navigator.clipboard.writeText(textToCopy || ""));
    actions.appendChild(copyBtn);

    container.appendChild(actions);
}

function renderFollowups(container, questions) {
    if (!questions || questions.length === 0) return;

    const wrap = document.createElement("div");
    wrap.className = "followup-questions";

    const label = document.createElement("div");
    label.className = "followup-label";
    label.textContent = "Related questions";
    wrap.appendChild(label);

    const list = document.createElement("div");
    list.className = "followup-list";

    questions.forEach(q => {
        const btn = document.createElement("button");
        btn.className = "followup-btn";
        btn.innerHTML = `
            <span class="followup-text"></span>
            <svg class="followup-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="M13 6l6 6-6 6"/></svg>
        `;
        btn.querySelector(".followup-text").textContent = q;
        btn.addEventListener("click", () => {
            questionInput.value = q;
            sendMessageStream();
        });
        list.appendChild(btn);
    });

    wrap.appendChild(list);
    container.appendChild(wrap);
}

// ============ Auth ============

function getToken() {
    return localStorage.getItem("access_token");
}

function setToken(token) {
    localStorage.setItem("access_token", token);
}

function clearToken() {
    localStorage.removeItem("access_token");
}

// Wrapper around fetch that automatically attaches the Authorization header.
// If the server ever responds 401 (missing/expired token), we drop the user
// back to the auth screen instead of leaving the app in a broken state.
async function authFetch(url, options = {}) {
    const token = getToken();
    const headers = { ...(options.headers || {}) };
    if (token) {
        headers["Authorization"] = `Bearer ${token}`;
    }

    const response = await fetch(url, { ...options, headers });

    if (response.status === 401) {
        clearToken();
        showAuthView();
        throw new Error("Session expired. Please log in again.");
    }

    return response;
}

function showAuthView() {
    authView.classList.remove("hidden");
    mainApp.classList.add("hidden");
}

function showMainApp() {
    authView.classList.add("hidden");
    mainApp.classList.remove("hidden");
    startNewChat();
    loadSessions();
}

function setAuthMode(mode) {
    authMode = mode;
    authError.textContent = "";
    if (mode === "login") {
        authSubtitle.textContent = "Sign in to continue";
        authSubmitBtn.textContent = "Log In";
        authToggleText.textContent = "Don't have an account?";
        authToggleLink.textContent = "Sign up";
    } else {
        authSubtitle.textContent = "Create your account";
        authSubmitBtn.textContent = "Sign Up";
        authToggleText.textContent = "Already have an account?";
        authToggleLink.textContent = "Log in";
    }
}

async function handleAuthSubmit(event) {
    event.preventDefault();

    const email = authEmail.value.trim();
    const password = authPassword.value;
    if (!email || !password) return;

    authError.textContent = "";
    authSubmitBtn.disabled = true;
    authSubmitBtn.textContent = authMode === "login" ? "Logging in..." : "Signing up...";

    const url = authMode === "login" ? AUTH_LOGIN_URL : AUTH_SIGNUP_URL;

    try {
        const response = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password }),
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || "Something went wrong.");
        }

        setToken(data.access_token);
        authForm.reset();
        showMainApp();

    } catch (error) {
        authError.textContent = error.message;
    }

    authSubmitBtn.disabled = false;
    setAuthMode(authMode);   // resets button text
}

function handleLogout() {
    clearToken();
    currentSessionId = null;
    showAuthView();
}

authForm.addEventListener("submit", handleAuthSubmit);

authToggleLink.addEventListener("click", (event) => {
    event.preventDefault();
    setAuthMode(authMode === "login" ? "signup" : "login");
});

logoutBtn.addEventListener("click", handleLogout);

// ============ Startup: show auth screen or main app depending on token ============
if (getToken()) {
    showMainApp();
} else {
    showAuthView();
}

function addMessage(message, type) {
    const messageDiv = document.createElement("div");
    messageDiv.className = `message ${type}`;

    const label = document.createElement("div");
    label.className = "message-label";
    label.innerHTML = type === "user"
        ? `<span class="name">You</span> · ${timeAgo()}`
        : `<span class="name">RAG Assistant</span> · ${timeAgo()}`;

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = message;

    messageDiv.appendChild(label);
    messageDiv.appendChild(bubble);
    chatBox.appendChild(messageDiv);

    chatBox.parentElement.scrollTop = chatBox.parentElement.scrollHeight;

    return { messageDiv, bubble };
}

function addTypingIndicator() {
    const messageDiv = document.createElement("div");
    messageDiv.className = "message bot";

    const label = document.createElement("div");
    label.className = "message-label";
    label.innerHTML = `<span class="name">RAG Assistant</span> · typing...`;

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.innerHTML = `<div class="typing-dots"><span></span><span></span><span></span></div>`;

    messageDiv.appendChild(label);
    messageDiv.appendChild(bubble);
    chatBox.appendChild(messageDiv);

    chatBox.parentElement.scrollTop = chatBox.parentElement.scrollHeight;

    return { messageDiv, bubble, label };
}

async function sendMessage() {
    const question = questionInput.value.trim();

    if (!question || isStreaming) {
        return;
    }

    isStreaming = true;
    addMessage(question, "user");

    questionInput.value = "";

    sendButton.disabled = true;

    const { bubble: botBubble, label: botLabel } = addTypingIndicator();

    try {
        const response = await authFetch(API_URL, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                question: question,
                session_id: currentSessionId
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP error: ${response.status}`);
        }

        const data = await response.json();

        const { text: cleanAnswer, citations } = extractCitations(data.answer || "No response received.");

        botLabel.innerHTML = `<span class="name">RAG Assistant</span> · ${timeAgo()}`;
        setRenderedContent(botBubble, cleanAnswer);

        renderCitations(botBubble, citations);
        renderMeta(botBubble, data);
        renderMessageActions(botBubble, data.answer || "");
        renderFollowups(botBubble, data.followup_questions);

        if (data.session_id) {
            currentSessionId = data.session_id;
            loadSessions();
        }

    } catch (error) {
        console.error(error);

        botBubble.innerHTML = "";
        botBubble.textContent = "Sorry, I couldn't connect to the backend.";
    }

    chatBox.parentElement.scrollTop = chatBox.parentElement.scrollHeight;

    isStreaming = false;
    sendButton.disabled = questionInput.value.trim().length === 0;

    questionInput.focus();
}

async function sendMessageStream() {
    const question = questionInput.value.trim();

    if (!question || isStreaming) {
        return;
    }

    isStreaming = true;
    addMessage(question, "user");

    questionInput.value = "";
    sendButton.disabled = true;

    const { bubble: botBubble, label: botLabel } = addTypingIndicator();

    let fullAnswer = "";
    let firstChunkReceived = false;
    let contentEl = null;
    let cursorEl = null;

    try {
        const response = await authFetch(STREAM_API_URL, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                question: question,
                session_id: currentSessionId
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP error: ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            const parts = buffer.split("\n\n");
            buffer = parts.pop();

            for (const part of parts) {
                if (!part.startsWith("data: ")) continue;

                const jsonStr = part.slice(6);
                const data = JSON.parse(jsonStr);

                if (data.chunk) {
                    if (!firstChunkReceived) {
                        botLabel.innerHTML = `<span class="name">RAG Assistant</span> · ${timeAgo()}`;
                        botBubble.innerHTML = "";

                        contentEl = document.createElement("div");
                        contentEl.className = "markdown-content";
                        cursorEl = document.createElement("span");
                        cursorEl.className = "stream-cursor";

                        botBubble.appendChild(contentEl);
                        botBubble.appendChild(cursorEl);

                        firstChunkReceived = true;
                    }
                    fullAnswer += data.chunk;
                    // Strip the "**Sources:**" footer as soon as it starts arriving so it
                    // never flashes as raw bold text mid-stream — it's rendered as cards below.
                    const { text: liveText } = extractCitations(fullAnswer);
                    setRenderedContent(contentEl, liveText);
                    chatBox.parentElement.scrollTop = chatBox.parentElement.scrollHeight;
                }

                if (data.done) {
                    if (cursorEl) {
                        cursorEl.remove();
                        cursorEl = null;
                    }

                    const { text: cleanAnswer, citations } = extractCitations(fullAnswer);
                    setRenderedContent(contentEl, cleanAnswer);

                    renderCitations(botBubble, citations);
                    renderMeta(botBubble, data);
                    renderMessageActions(botBubble, cleanAnswer);
                    renderFollowups(botBubble, data.followup_questions);

                    if (data.session_id) {
                        currentSessionId = data.session_id;
                        loadSessions();
                    }
                }
            }
        }

    } catch (error) {
        console.error(error);
        botBubble.innerHTML = "";
        botBubble.textContent = "Sorry, I couldn't connect to the backend.";
    }

    chatBox.parentElement.scrollTop = chatBox.parentElement.scrollHeight;

    isStreaming = false;
    sendButton.disabled = questionInput.value.trim().length === 0;

    questionInput.focus();
}

async function loadSessions() {
    try {
        const response = await authFetch(SESSIONS_API_URL);
        if (!response.ok) throw new Error(`HTTP error: ${response.status}`);

        const sessions = await response.json();

        sessionsList.innerHTML = "";

        sessions.forEach(session => {
            const item = document.createElement("div");
            item.className = "session-item";
            if (session.session_id === currentSessionId) {
                item.classList.add("active");
            }
            item.textContent = session.title || "New Chat";
            item.addEventListener("click", () => loadSessionMessages(session.session_id));
            sessionsList.appendChild(item);
        });

    } catch (error) {
        console.error("Failed to load sessions:", error);
    }
}

async function loadSessionMessages(sessionId) {
    try {
        const response = await authFetch(`${SESSIONS_API_URL}/${sessionId}`);
        if (!response.ok) throw new Error(`HTTP error: ${response.status}`);

        const data = await response.json();

        currentSessionId = sessionId;
        chatBox.innerHTML = "";
        showChatView();

        data.messages.forEach(msg => {
            const type = msg.role === "user" ? "user" : "bot";
            const { bubble } = addMessage(msg.content, type);
            if (type === "bot") {
                setRenderedContent(bubble, msg.content);
            }
        });

        // addMessage() scrolls to the bottom using each message's raw-text height,
        // before markdown/KaTeX rendering grows it — so the last render can leave the
        // view stuck mid-message. Re-scroll once now that every message is fully rendered.
        chatBox.parentElement.scrollTop = chatBox.parentElement.scrollHeight;

        loadSessions();

    } catch (error) {
        console.error("Failed to load session:", error);
    }
}

function showChatView() {
    chatBoxContainer.style.display = "";
    inputArea.style.display = "";
    documentsView.classList.add("hidden");
    headerTitle.textContent = "RAG Assistant";
    newChatBtn.classList.add("active");
    documentsBtn.classList.remove("active");
}

function showDocumentsView() {
    chatBoxContainer.style.display = "none";
    inputArea.style.display = "none";
    documentsView.classList.remove("hidden");
    headerTitle.textContent = "Documents";
    documentsBtn.classList.add("active");
    newChatBtn.classList.remove("active");
    loadDocuments();
}

function startNewChat() {
    currentSessionId = null;
    chatBox.innerHTML = "";
    questionInput.value = "";
    sendButton.disabled = true;
    showChatView();
    loadSessions();
    questionInput.focus();
}

const DOCUMENT_DELETE_ICON = `
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 6h18"/>
        <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
        <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
    </svg>
`;

const DOCUMENT_ICON = `
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <path d="M14 2v6h6"/>
    </svg>
`;

const TABLE_ICON = `
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="3" y="3" width="18" height="18" rx="2"/>
        <line x1="3" y1="9" x2="21" y2="9"/>
        <line x1="3" y1="15" x2="21" y2="15"/>
        <line x1="9" y1="3" x2="9" y2="21"/>
    </svg>
`;

async function loadDocuments() {
    documentsList.innerHTML = `<div class="documents-empty">Loading...</div>`;

    try {
        const [docsResponse, tablesResponse] = await Promise.all([
            authFetch(DOCUMENTS_API_URL),
            authFetch(TABLES_API_URL),
        ]);

        if (!docsResponse.ok) throw new Error(`HTTP error: ${docsResponse.status}`);
        if (!tablesResponse.ok) throw new Error(`HTTP error: ${tablesResponse.status}`);

        const documents = await docsResponse.json();
        const tables = await tablesResponse.json();

        const items = [
            ...documents.map(doc => ({ type: "document", ...doc })),
            ...tables.map(tbl => ({ type: "table", ...tbl })),
        ];

        if (items.length === 0) {
            documentsList.innerHTML = `<div class="documents-empty">No documents uploaded yet.</div>`;
            return;
        }

        documentsList.innerHTML = "";

        items.forEach(item => {
            const row = document.createElement("div");
            row.className = "document-row";

            const info = document.createElement("div");
            info.className = "document-info";

            if (item.type === "document") {
                info.innerHTML = `
                    ${DOCUMENT_ICON}
                    <div>
                        <div class="document-name">${escapeHtml(item.filename)}</div>
                        <div class="document-meta">${item.chunk_count} chunk${item.chunk_count === 1 ? "" : "s"}</div>
                    </div>
                `;
            } else {
                const columnNames = item.columns.map(c => c.name).join(", ");
                info.innerHTML = `
                    ${TABLE_ICON}
                    <div>
                        <div class="document-name">${escapeHtml(item.table_name)}</div>
                        <div class="document-meta">${item.row_count ?? "?"} rows · ${escapeHtml(columnNames)}</div>
                    </div>
                `;
            }

            const deleteBtn = document.createElement("button");
            deleteBtn.className = "document-delete-btn";
            deleteBtn.title = "Delete";
            deleteBtn.innerHTML = DOCUMENT_DELETE_ICON;

            let confirmTimeout = null;
            deleteBtn.addEventListener("click", () => {
                if (!deleteBtn.classList.contains("confirming")) {
                    deleteBtn.classList.add("confirming");
                    deleteBtn.textContent = "Confirm?";
                    confirmTimeout = setTimeout(() => {
                        deleteBtn.classList.remove("confirming");
                        deleteBtn.innerHTML = DOCUMENT_DELETE_ICON;
                    }, 3000);
                    return;
                }

                clearTimeout(confirmTimeout);
                if (item.type === "document") {
                    deleteDocument(item.document_id, deleteBtn);
                } else {
                    deleteTable(item.table_name, deleteBtn);
                }
            });

            row.appendChild(info);
            row.appendChild(deleteBtn);
            documentsList.appendChild(row);
        });

    } catch (error) {
        console.error("Failed to load documents:", error);
        documentsList.innerHTML = `<div class="documents-empty">Failed to load documents.</div>`;
    }
}

async function deleteDocument(documentId, deleteBtn) {
    deleteBtn.disabled = true;

    try {
        const response = await authFetch(`${DOCUMENTS_API_URL}/${encodeURIComponent(documentId)}`, {
            method: "DELETE",
        });

        if (!response.ok) throw new Error(`HTTP error: ${response.status}`);

        loadDocuments();
    } catch (error) {
        console.error("Failed to delete document:", error);
        deleteBtn.disabled = false;
        deleteBtn.classList.remove("confirming");
        deleteBtn.innerHTML = DOCUMENT_DELETE_ICON;
        uploadStatusEl.textContent = "Failed to delete document. Please try again.";
        uploadStatusEl.className = "upload-status error";
    }
}

async function deleteTable(tableName, deleteBtn) {
    deleteBtn.disabled = true;

    try {
        const response = await authFetch(`${TABLES_API_URL}/${encodeURIComponent(tableName)}`, {
            method: "DELETE",
        });

        if (!response.ok) throw new Error(`HTTP error: ${response.status}`);

        loadDocuments();
    } catch (error) {
        console.error("Failed to delete table:", error);
        deleteBtn.disabled = false;
        deleteBtn.classList.remove("confirming");
        deleteBtn.innerHTML = DOCUMENT_DELETE_ICON;
        uploadStatusEl.textContent = "Failed to delete table. Please try again.";
        uploadStatusEl.className = "upload-status error";
    }
}

async function uploadDocument(file) {
    const isExcel = /\.(xlsx|xls)$/i.test(file.name);
    const uploadUrl = isExcel ? TABLES_API_URL : DOCUMENTS_API_URL;

    uploadStatusEl.textContent = `Uploading "${file.name}"...`;
    uploadStatusEl.className = "upload-status uploading";

    const formData = new FormData();
    formData.append("file", file);

    try {
        const response = await authFetch(uploadUrl, {
            method: "POST",
            body: formData,
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || `HTTP error: ${response.status}`);
        }

        if (isExcel) {
            uploadStatusEl.textContent = `"${data.table_name}" added — ${data.row_count} rows indexed.`;
        } else {
            uploadStatusEl.textContent = `"${data.filename}" added — ${data.chunk_count} chunks indexed.`;
        }
        uploadStatusEl.className = "upload-status success";
        loadDocuments();

    } catch (error) {
        console.error("Upload failed:", error);
        uploadStatusEl.textContent = `Upload failed: ${error.message}`;
        uploadStatusEl.className = "upload-status error";
    }
}

documentsBtn.addEventListener("click", showDocumentsView);

pdfUploadInput.addEventListener("change", () => {
    const file = pdfUploadInput.files[0];
    pdfUploadInput.value = "";
    if (file) {
        uploadDocument(file);
    }
});

newChatBtn.addEventListener("click", startNewChat);

sendButton.addEventListener("click", sendMessageStream);

questionInput.addEventListener("keydown", function(event) {
    if (event.key === "Enter" && !isStreaming) {
        sendMessageStream();
    }
});

questionInput.addEventListener("input", function() {
    sendButton.disabled = isStreaming || questionInput.value.trim().length === 0;
});

// Voice input via the browser's native Web Speech API — no backend, no library.
const SpeechRecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;

if (SpeechRecognitionCtor) {
    const recognition = new SpeechRecognitionCtor();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = navigator.language || "en-US";

    let isListening = false;
    let baseText = "";

    recognition.addEventListener("start", () => {
        isListening = true;
        baseText = questionInput.value.trim();
        micButton.classList.add("listening");
    });

    recognition.addEventListener("result", (event) => {
        let transcript = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
            transcript += event.results[i][0].transcript;
        }
        questionInput.value = baseText ? `${baseText} ${transcript}` : transcript;
        sendButton.disabled = isStreaming || questionInput.value.trim().length === 0;
    });

    recognition.addEventListener("end", () => {
        isListening = false;
        micButton.classList.remove("listening");
        questionInput.focus();
    });

    recognition.addEventListener("error", (event) => {
        console.error("Speech recognition error:", event.error);
        isListening = false;
        micButton.classList.remove("listening");
    });

    micButton.addEventListener("click", () => {
        if (isStreaming) return;

        if (isListening) {
            recognition.stop();
        } else {
            try {
                recognition.start();
            } catch (err) {
                console.error("Could not start speech recognition:", err);
            }
        }
    });
} else {
    micButton.disabled = true;
    micButton.title = "Voice input isn't supported in this browser";
}