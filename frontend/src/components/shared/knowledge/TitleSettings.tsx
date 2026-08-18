import { RiBookReadLine, RiEdit2Line } from "@remixicon/react";
import { useState, useRef, useEffect } from "react";

interface TitleSettingsProps {
	title: string;
	onChangeTitle: (newTitle: string) => void;
	onSave?: (newTitle?: string) => void;
	onCancel?: () => void;
}

export function TitleSettings({ title, onChangeTitle, onSave }: TitleSettingsProps) {
	const [localTitle, setLocalTitle] = useState(title);
	const [isLocalEditing, setIsLocalEditing] = useState(false);
	const [prevTitle, setPrevTitle] = useState(title);
	const inputRef = useRef<HTMLInputElement>(null);

	if (title !== prevTitle) {
		setPrevTitle(title);
		setLocalTitle(title);
	}

	useEffect(() => {
		if (isLocalEditing && inputRef.current) {
			inputRef.current.focus();
		}
	}, [isLocalEditing]);

	// If the parent enters Edit Mode, we don't strictly have to enter local edit mode,
	// because the user's design has an explicit edit pencil button.
	// But we only show this component if we want to allow title edits.
	// We'll show it always, since the parent (ChatPreview) might render it unconditionally.

	const handleSave = () => {
		setIsLocalEditing(false);
		onChangeTitle(localTitle);
		if (onSave) {
			onSave(localTitle);
		}
	};

	const handleCancel = () => {
		setIsLocalEditing(false);
		setLocalTitle(title);
	};

	if (isLocalEditing) {
		return (
			<div className="flex items-center gap-2 w-fit max-w-full">
				<div className="flex items-center gap-2 px-3 py-2 border border-zinc-200 rounded-md bg-white transition-colors flex-1 min-w-0 overflow-hidden">
					<RiBookReadLine className="size-4 text-zinc-400 shrink-0" />
					<div className="relative inline-grid items-center min-w-0 overflow-hidden flex-1">
						<span className="invisible whitespace-pre text-[13px] font-medium col-start-1 row-start-1 pr-1 truncate">
							{localTitle || " "}
						</span>
						<input 
							ref={inputRef}
							className="text-[13px] font-medium text-zinc-950 outline-none w-full bg-transparent col-start-1 row-start-1 min-w-0"
							value={localTitle}
							onChange={(e) => setLocalTitle(e.target.value)}
							onBlur={handleSave}
							onKeyDown={(e) => {
								if (e.key === 'Enter') handleSave();
								if (e.key === 'Escape') handleCancel();
							}}
						/>
					</div>
				</div>
				<button 
					onMouseDown={(e) => {
						e.preventDefault();
						handleCancel();
					}} 
					className="px-3 py-2 text-[13px] font-medium border border-zinc-200 bg-white text-zinc-700 rounded-md hover:bg-zinc-50 transition-colors shrink-0"
				>
					Cancel
				</button>
				<button 
					onMouseDown={(e) => {
						e.preventDefault();
						handleSave();
					}} 
					className="px-3 py-2 text-[13px] font-medium bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors shrink-0 shadow-sm"
				>
					Save
				</button>
			</div>
		);
	}

	return (
		<div className="flex items-center gap-2 w-fit max-w-full">
			<div className="flex items-center gap-2 px-3 py-2 border border-zinc-200 rounded-md bg-white flex-1 min-w-0 overflow-hidden">
				<RiBookReadLine className="size-4 text-zinc-900 shrink-0" />
				<span className="text-[13px] font-medium text-zinc-950 truncate min-w-0">{localTitle}</span>
			</div>
			<button 
				onClick={() => setIsLocalEditing(true)} 
				className="p-2 border border-zinc-200 rounded-md bg-white hover:bg-zinc-50 transition-colors text-zinc-700 shrink-0"
			>
				<RiEdit2Line className="size-4" />
			</button>
		</div>
	);
}
