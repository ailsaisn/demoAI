"use client";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { RiCheckLine } from "@remixicon/react";
import { useState, useEffect } from "react";
import { UserResponse } from "../api/types";
import { useCategories } from "../../category/hooks/use-categories";
import { useUpdateDoctorCategories } from "../hooks/use-users";

export function DoctorManageKnowledgeDialog({
  isOpen,
  onOpenChange,
  doctor,
}: {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  doctor: UserResponse | null;
}) {
  const { data: categories = [] } = useCategories();
  const updateCategories = useUpdateDoctorCategories();
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  useEffect(() => {
    if (isOpen && doctor) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelectedIds(doctor.categories?.map((c) => c.id) || []);
    }
  }, [isOpen, doctor]);

  const handleToggle = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]
    );
  };

  const handleSave = () => {
    if (doctor) {
      updateCategories.mutate(
        { userId: doctor.id, categories: selectedIds },
        {
          onSuccess: () => {
            onOpenChange(false);
          },
        }
      );
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md p-0 flex flex-col gap-0 rounded-lg overflow-hidden bg-white border border-gray-200 shadow-none">
        <DialogHeader className="p-4 border-b border-gray-100 flex flex-row items-center justify-between">
          <DialogTitle className="text-base font-semibold text-foreground">
            Manage Knowledge Base
          </DialogTitle>
        </DialogHeader>

        <div className="p-4 flex flex-col gap-4 max-h-[60vh] overflow-y-auto">
          {/* List of knowledge */}
          <div className="flex flex-col gap-3">
            {categories.length === 0 && (
              <div className="text-sm text-muted-foreground text-center py-4">
                No knowledge categories available.
              </div>
            )}
            {categories.map((category) => {
              const isSelected = selectedIds.includes(category.id);
              return (
                <div
                  key={category.id}
                  className={`border rounded-lg p-3 flex items-center justify-between cursor-pointer transition-colors ${
                    isSelected
                      ? "border-blue-500 bg-blue-50/60"
                      : "border-gray-200 hover:bg-zinc-50"
                  }`}
                  onClick={() => handleToggle(category.id)}
                >
                  <div className="flex items-center gap-3 w-full">
                    <Checkbox
                      id={`knowledge-${category.id}`}
                      checked={isSelected}
                      onCheckedChange={() => handleToggle(category.id)}
                      className="data-[state=checked]:bg-blue-600 data-[state=checked]:border-blue-600"
                    />
                    <div className="flex flex-col">
                      <span className="text-sm font-medium text-foreground">
                        {category.name}
                      </span>
                      {category.description && (
                        <span className="text-xs text-muted-foreground line-clamp-1">
                          {category.description}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-900 leading-relaxed">
            Choose one or more knowledge bases to assign to the doctor, ensuring the chatbot only responds with relevant information.
          </div>
        </div>

        <div className="p-4 border-t border-gray-100 flex items-center justify-end gap-2 bg-zinc-50/50">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={updateCategories.isPending}
            className="border-gray-200 bg-white text-zinc-700 hover:bg-zinc-50 rounded-lg px-4 h-10 font-medium text-sm transition-colors cursor-pointer shadow-none"
          >
            Cancel
          </Button>
          <Button
            className="bg-blue-600 text-white hover:bg-blue-700 px-4 h-10 rounded-lg font-medium text-sm transition-colors cursor-pointer shadow-none disabled:opacity-50"
            onClick={handleSave}
            disabled={updateCategories.isPending}
          >
            <RiCheckLine className="mr-1.5 h-4 w-4" />
            Save Knowledge
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
