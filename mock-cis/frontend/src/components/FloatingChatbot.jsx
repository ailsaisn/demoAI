import { useEffect, useRef, useState } from "react";
import "./FloatingChatbot.css";

/**
 * FloatingChatbot Component
 *
 * A reference implementation for integrating the Arya Noble AI Chatbot into a React application.
 *
 * @param {Object} props
 * @param {string} props.token - The JWT token provided by the CIS system (used for authorization).
 * @param {string} props.doctorName - The name of the doctor currently logged in (for display).
 * @param {string} [props.branchCode] - The code of the branch (e.g. "011").
 * @param {string} [props.branchId] - The CIS external ID of the branch (e.g. "838").
 * @param {string} [props.apiBaseUrl] - The base URL of the Chatbot API (e.g., https://api.arya-noble.com).
 */
export default function FloatingChatbot({
	token,
	doctorName = "Doctor",
	branchCode,
	branchId,
	apiBaseUrl = "http://localhost:8000",
}) {
	const [isOpen, setIsOpen] = useState(false);
	const [messages, setMessages] = useState([]);
	const [input, setInput] = useState("");
	const [sessionId, setSessionId] = useState(null);
	const [sessionStatus, setSessionStatus] = useState("ACTIVE");
	const [isLoading, setIsLoading] = useState(false);

	// Feedback states
	const [rating, setRating] = useState(null);
	const [feedbackText, setFeedbackText] = useState("");
	const [dataNotFound, setDataNotFound] = useState(false);
	const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);
	const [manualClose, setManualClose] = useState(false);

	const chatEndRef = useRef(null);

	useEffect(() => {
		chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
	}, [messages]);

	const initChat = async () => {
		try {
			const res = await fetch(`${apiBaseUrl}/api/chats/`, {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${token}`,
				},
				body: JSON.stringify({
					...(branchCode ? { branch_code: branchCode } : {}),
					...(branchId && !branchCode ? { cis_branch_id: branchId } : {}),
				}),
			});

			if (!res.ok) {
				const errData = await res.json().catch(() => ({}));
				throw new Error(errData.detail || "Failed to initialize session");
			}

			const data = await res.json();
			setSessionId(data.id);
			setSessionStatus(data.status || "ACTIVE");

			// Fetch existing messages if resuming an active session
			const msgRes = await fetch(`${apiBaseUrl}/api/chats/${data.id}/messages`, {
				headers: { Authorization: `Bearer ${token}` },
				cache: "no-store"
			});

			if (msgRes.ok) {
				const history = await msgRes.json();
				if (history && history.length > 0) {
					setMessages(
						history.map((m) => ({
							id: m.id,
							role: m.role.toLowerCase(),
							content: m.content,
						})),
					);
				} else {
					setMessages([
						{
							id: "init",
							role: "assistant",
							content: "Your artificial intelligence assistant is ready.",
						},
					]);
				}
			}
		} catch (err) {
			console.error("Failed to create/resume session:", err);
			setMessages([
				{
					id: "init-error",
					role: "assistant",
					content: `Error initializing session: ${err.message}`,
				},
			]);
		}
	};

	const toggleChat = async () => {
		const nextState = !isOpen;
		setIsOpen(nextState);

		// Step 1: If opening for the first time, create a new chat session via the API
		if (nextState && !sessionId && token) {
			await initChat();
		}
	};

	const startNewChat = async () => {
		setRating(null);
		setFeedbackText("");
		setDataNotFound(false);
		setFeedbackSubmitted(false);
		setManualClose(false);
		setSessionId(null);
		setMessages([]);
		await initChat();
	};

	const handleSend = async (e) => {
		e.preventDefault();
		if (!input.trim() || !sessionId || !token || isLoading) return;

		const userMessage = { id: Date.now().toString(), role: "user", content: input };
		setMessages((prev) => [...prev, userMessage]);
		setInput("");
		setIsLoading(true);

		try {
			const payload = JSON.stringify({
				role: "user",
				content: userMessage.content
			});

			const res = await fetch(`${apiBaseUrl}/api/chats/${sessionId}/messages/stream`, {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${token}`,
				},
				body: payload,
			});

			if (!res.ok) {
				const errorData = await res.json().catch(() => ({}));
				throw new Error(errorData.detail || "Failed to send message");
			}

			if (!res.body) throw new Error("ReadableStream not supported");

			const reader = res.body.getReader();
			const decoder = new TextDecoder("utf-8");
			let assistantMessageId = "ai-" + Date.now().toString();

			// Create a placeholder for the assistant message
			setMessages((prev) => [...prev, { id: assistantMessageId, role: "assistant", content: "" }]);
			setIsLoading(false); // Remove loading indicator once stream starts

			let buffer = "";

			while (true) {
				const { value, done } = await reader.read();
				if (done) break;

				buffer += decoder.decode(value, { stream: true });
				const events = buffer.split("\n\n");

				// Keep the last segment in the buffer because it might be incomplete
				buffer = events.pop() || "";

				for (let event of events) {
					event = event.trim();
					if (!event) continue;

					if (event.startsWith("data: ")) {
						const jsonStr = event.substring(6).trim();
						if (!jsonStr) continue;

						try {
							const parsedData = JSON.parse(jsonStr);

							if (parsedData.type === "token") {
								setMessages((prev) =>
									prev.map((msg) =>
										msg.id === assistantMessageId
											? { ...msg, content: msg.content + parsedData.content }
											: msg,
									),
								);
							} else if (parsedData.type === "done") {
								// The stream has ended
								break;
							} else if (parsedData.error) {
								console.error("AI Assistant Error:", parsedData.error);
								setMessages((prev) =>
									prev.map((msg) =>
										msg.id === assistantMessageId
											? { ...msg, content: msg.content + "\n\n**Error:** " + parsedData.error }
											: msg,
									),
								);
							}
							// 'context' type could be handled here if we want to show sources
						} catch (err) {
							console.error("Failed to parse SSE JSON chunk", err, "Chunk:", jsonStr);
						}
					}
				}
			}
		} catch (err) {
			console.error("Message send error:", err);
			setIsLoading(false);
			
			if (err.message.toLowerCase().includes("closed") || err.message.toLowerCase().includes("expired") || err.message.includes("403")) {
				setSessionStatus("CLOSED");
				setManualClose(false); // Indicates it was a timeout, not a manual click
			} else {
				setMessages((prev) => [
					...prev,
					{
						id: "error-" + Date.now(),
						role: "assistant",
						content: `An error occurred: ${err.message}`,
					},
				]);
			}
		}
	};

	const endChat = async () => {
		if (!sessionId || !token) return;
		try {
			setManualClose(true);
			const res = await fetch(`${apiBaseUrl}/api/chats/${sessionId}`, {
				method: "PUT",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${token}`,
				},
				body: JSON.stringify({ status: "CLOSED" }),
			});
			if (res.ok) {
				setSessionStatus("CLOSED");
			}
		} catch (err) {
			console.error("Failed to end chat:", err);
		}
	};

	const submitFeedback = async (e) => {
		if (e) e.preventDefault();
		if (!sessionId || !token || !rating) return;
		try {
			await fetch(`${apiBaseUrl}/api/chats/${sessionId}`, {
				method: "PUT",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${token}`,
				},
				body: JSON.stringify({
					rating: rating,
					feedback: feedbackText,
					has_data_issue: dataNotFound,
				}),
			});
			setFeedbackSubmitted(true);
		} catch (err) {
			console.error("Failed to submit feedback:", err);
		}
	};

	return (
		<div className="fc-container">
			{/* Expanded Widget */}
			<div className={`fc-window ${isOpen ? "fc-open" : "fc-closed"}`}>
				{/* Header */}
				<div className="fc-header">
					<div className="fc-header-left">
						<div className="fc-header-icon">
							{/* Robot icon */}
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 24 24"
								fill="currentColor"
								width="20"
								height="20"
							>
								<path d="M13.5 2C13.5 2.44425 13.3069 2.84339 13 3.11805V5H18C19.6569 5 21 6.34315 21 8V18C21 19.6569 19.6569 21 18 21H6C4.34315 21 3 19.6569 3 18V8C3 6.34315 4.34315 5 6 5H11V3.11805C10.6931 2.84339 10.5 2.44425 10.5 2C10.5 1.17157 11.1716 0.5 12 0.5C12.8284 0.5 13.5 1.17157 13.5 2ZM6 7C5.44772 7 5 7.44772 5 8V18C5 18.5523 5.44772 19 6 19H18C18.5523 19 19 18.5523 19 18V8C19 7.44772 18.5523 7 18 7H13H11H6ZM2 10H0V16H2V10ZM22 10H24V16H22V10ZM9 14.5C9.82843 14.5 10.5 13.8284 10.5 13C10.5 12.1716 9.82843 11.5 9 11.5C8.17157 11.5 7.5 12.1716 7.5 13C7.5 13.8284 8.17157 14.5 9 14.5ZM15 14.5C15.8284 14.5 16.5 13.8284 16.5 13C16.5 12.1716 15.8284 11.5 15 11.5C14.1716 11.5 13.5 12.1716 13.5 13C13.5 13.8284 14.1716 14.5 15 14.5Z" />
							</svg>
						</div>
						<div className="fc-header-title">
							<h3>Erha AI Assistant</h3>
							<span>{doctorName}</span>
						</div>
					</div>
					<div className="fc-header-actions">
						{sessionStatus === "ACTIVE" && (
							<button onClick={endChat} className="fc-action-btn fc-end-btn" title="End Chat">
								End
							</button>
						)}
						<button onClick={() => setIsOpen(false)} className="fc-action-btn" title="Minimize">
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 24 24"
								fill="currentColor"
								width="20"
								height="20"
							>
								<path d="M12 10.586l4.95-4.95 1.414 1.414-4.95 4.95 4.95 4.95-1.414 1.414-4.95-4.95-4.95 4.95-1.414-1.414 4.95-4.95-4.95-4.95L7.05 5.636z" />
							</svg>
						</button>
					</div>
				</div>

				{sessionStatus === "CLOSED" ? (
					<div className="fc-end-session-screen">
						<h2 className="fc-end-title">End of Session</h2>
						<div className="fc-end-icon">
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								strokeWidth="2"
								strokeLinecap="round"
								strokeLinejoin="round"
							>
								<circle cx="12" cy="12" r="10"></circle>
								<polyline points="12 6 12 12 16 14"></polyline>
							</svg>
						</div>
						<p className="fc-end-desc">
							{manualClose
								? "This session has ended, please give a feedback so we can improve, and you will get a summary."
								: "You have reached the 5-minute limit for this session, please give this session a feedback so we can improve, and you will get a summary."}
						</p>

						{feedbackSubmitted ? (
							<div className="fc-feedback-thanks">
								<p>Thank you for your feedback!</p>
								<button 
									onClick={startNewChat}
									className="fc-submit-feedback-btn"
									style={{marginTop: '1rem'}}
								>
									Start New Chat
								</button>
							</div>
						) : (
							<div className="fc-feedback-card">
								<div className="fc-form-group">
									<label>
										Rate<span className="text-red-500">*</span>
									</label>
									<div className="fc-rating-buttons">
										<button
											type="button"
											className={`fc-rate-btn ${rating === "GOOD" ? "active" : ""}`}
											onClick={() => setRating("GOOD")}
										>
											<svg
												xmlns="http://www.w3.org/2000/svg"
												viewBox="0 0 24 24"
												fill="none"
												stroke="currentColor"
												strokeWidth="2"
												strokeLinecap="round"
												strokeLinejoin="round"
												className="size-4"
											>
												<path d="M7 10v12" />
												<path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2h0a3.13 3.13 0 0 1 3 3.88Z" />
											</svg>
											Good
										</button>
										<button
											type="button"
											className={`fc-rate-btn ${rating === "BAD" ? "active" : ""}`}
											onClick={() => setRating("BAD")}
										>
											<svg
												xmlns="http://www.w3.org/2000/svg"
												viewBox="0 0 24 24"
												fill="none"
												stroke="currentColor"
												strokeWidth="2"
												strokeLinecap="round"
												strokeLinejoin="round"
												className="size-4"
											>
												<path d="M17 14V2" />
												<path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22h0a3.13 3.13 0 0 1-3-3.88Z" />
											</svg>
											Bad
										</button>
									</div>
								</div>

								<div className="fc-form-group">
									<label>
										Feedback <span className="fc-optional">(opsional)</span>
									</label>
									<textarea
										placeholder="write your feedback here..."
										value={feedbackText}
										onChange={(e) => setFeedbackText(e.target.value)}
									></textarea>
								</div>

								<label className="fc-checkbox-label">
									<input
										type="checkbox"
										checked={dataNotFound}
										onChange={(e) => setDataNotFound(e.target.checked)}
									/>
									I found a "Data Not Found" issue in this chat.
								</label>

								<button
									type="button"
									className="fc-submit-feedback-btn"
									onClick={submitFeedback}
									disabled={!rating}
								>
									Send Feedback
								</button>
							</div>
						)}
					</div>
				) : (
					<>
						{/* Chat Area */}
						<div className="fc-body">
							{messages.map((msg, index) => (
								<div
									key={msg.id || index}
									className={`fc-message-row ${msg.role === "user" ? "fc-row-user" : "fc-row-assistant"}`}
								>
									<div className={`fc-bubble ${msg.role === "user" ? "fc-user" : "fc-assistant"}`}>
										{msg.content}
									</div>
								</div>
							))}
							{isLoading && (
								<div className="fc-message-row fc-row-assistant">
									<div className="fc-bubble fc-assistant fc-loading">
										<div className="fc-dot"></div>
										<div className="fc-dot"></div>
										<div className="fc-dot"></div>
									</div>
								</div>
							)}
							<div ref={chatEndRef} />
						</div>

						{/* Input Area */}
						<div className="fc-footer">
							<form onSubmit={handleSend} className="fc-input-wrapper">
								<input
									type="text"
									value={input}
									onChange={(e) => setInput(e.target.value)}
									placeholder="Describe what your concern is..."
									disabled={isLoading || !sessionId}
								/>
								<button type="submit" disabled={isLoading || !input.trim() || !sessionId}>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										viewBox="0 0 24 24"
										fill="currentColor"
										width="20"
										height="20"
									>
										<path d="M1.946 9.315c-.522-.174-.527-.455.01-.634l19.087-6.362c.529-.176.832.12.684.638l-5.454 19.086c-.15.529-.455.547-.679.045L12 14l6-8-8 6-8.054-2.685z" />
									</svg>
								</button>
							</form>
						</div>
					</>
				)}
			</div>

			{/* Minimized Button */}
			{!isOpen && (
				<button className="fc-toggle" onClick={toggleChat} aria-label="Open AI Assistant">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 24 24"
						fill="currentColor"
						width="24"
						height="24"
					>
						<path d="M13.5 2C13.5 2.44425 13.3069 2.84339 13 3.11805V5H18C19.6569 5 21 6.34315 21 8V18C21 19.6569 19.6569 21 18 21H6C4.34315 21 3 19.6569 3 18V8C3 6.34315 4.34315 5 6 5H11V3.11805C10.6931 2.84339 10.5 2.44425 10.5 2C10.5 1.17157 11.1716 0.5 12 0.5C12.8284 0.5 13.5 1.17157 13.5 2ZM6 7C5.44772 7 5 7.44772 5 8V18C5 18.5523 5.44772 19 6 19H18C18.5523 19 19 18.5523 19 18V8C19 7.44772 18.5523 7 18 7H13H11H6ZM2 10H0V16H2V10ZM22 10H24V16H22V10ZM9 14.5C9.82843 14.5 10.5 13.8284 10.5 13C10.5 12.1716 9.82843 11.5 9 11.5C8.17157 11.5 7.5 12.1716 7.5 13C7.5 13.8284 8.17157 14.5 9 14.5ZM15 14.5C15.8284 14.5 16.5 13.8284 16.5 13C16.5 12.1716 15.8284 11.5 15 11.5C14.1716 11.5 13.5 12.1716 13.5 13C13.5 13.8284 14.1716 14.5 15 14.5Z" />
					</svg>
				</button>
			)}
		</div>
	);
}
