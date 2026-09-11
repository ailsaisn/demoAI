"use client";

import React, { useEffect, useState, useRef } from "react";
import { MarkdownContent } from "./markdown-content";

export interface StreamingMarkdownProps {
	content: string;
	animate?: boolean;
	speed?: number; // ms per step
	wordsPerStep?: number;
	onFinished?: () => void;
	className?: string;
}

export function StreamingMarkdown({
	content,
	animate = false,
	speed = 18,
	wordsPerStep = 4,
	onFinished,
	className,
}: StreamingMarkdownProps) {
	const [displayedLength, setDisplayedLength] = useState(animate ? 0 : content.length);
	const [isStreaming, setIsStreaming] = useState(animate);
	const onFinishedRef = useRef(onFinished);

	useEffect(() => {
		onFinishedRef.current = onFinished;
	}, [onFinished]);

	useEffect(() => {
		if (!animate || !content) return;

		// Split text by whitespace to stream word by word
		const words = content.split(/(\s+)/);
		let currentWordIdx = 0;

		const interval = setInterval(() => {
			currentWordIdx = Math.min(words.length, currentWordIdx + wordsPerStep);
			const currentText = words.slice(0, currentWordIdx).join("");
			setDisplayedLength(currentText.length);

			if (currentWordIdx >= words.length) {
				clearInterval(interval);
				setIsStreaming(false);
				onFinishedRef.current?.();
			}
		}, speed);

		return () => {
			clearInterval(interval);
		};
	}, [content, animate, speed, wordsPerStep]);

	const displayedText = animate && isStreaming ? content.substring(0, displayedLength) : content;

	return (
		<div className={className}>
			<MarkdownContent content={displayedText} />
			{animate && isStreaming && (
				<span
					className="inline-block w-1.5 h-4 ml-0.5 bg-blue-600 animate-pulse rounded-xs align-middle"
					aria-hidden="true"
				/>
			)}
		</div>
	);
}
