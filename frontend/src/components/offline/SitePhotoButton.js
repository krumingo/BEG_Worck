// PWA-02 — a site photo: uploaded at once when online (/media/upload); without a connection
// it is kept encrypted on the phone with its SHA-256 and waits („Чака качване на файл“) —
// without a File Registry it never becomes final (orchestrator Q1).
import { useRef, useState } from "react";
import { Camera } from "lucide-react";
import { toast } from "sonner";
import API from "@/lib/api";
import { sendOrQueue, STATUS } from "@/lib/offline";
import { sha256Hex } from "@/lib/offline/crypto";
import { Button } from "@/components/ui/button";

// FG-637: the same limits as the server's upload guard (/media/upload and the offline photo)
export const PHOTO_MAX = 10 * 1024 * 1024;
export const PHOTO_TYPES = ["image/jpeg", "image/png", "image/webp", "image/heic"];

export function photoProblem(file) {
  if (!PHOTO_TYPES.includes(file.type)) return "Само снимка (JPEG, PNG, WebP, HEIC)";
  if (file.size > PHOTO_MAX) return "Снимката е по-голяма от 10 MB";
  return null;
}

export default function SitePhotoButton({ projectId, allowed = true, className = "" }) {
  const input = useRef(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState(null);
  // FG-639: hidden where the server would refuse the photo (role / not on the project)
  if (allowed === false) return null;
  const onFile = async (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!file || !projectId) return;
    // told at capture, on screen (the app shows no toasts — HANDOFF D12)
    const why = photoProblem(file);
    setProblem(why);
    if (why) return;
    setBusy(true);
    try {
      const sha256 = await sha256Hex(file);
      const r = await sendOrQueue({
        opType: "media.upload",
        projectId,
        file,
        payload: { sha256, size: file.size, mime: file.type, filename: file.name,
          context_type: "project", context_id: projectId },
        send: () => {
          const fd = new FormData();
          fd.append("file", file);
          fd.append("context_type", "project");
          fd.append("context_id", projectId);
          return API.post("/media/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
        },
      });
      toast.success(r.queued ? STATUS.saved : "Снимката е качена");
    } catch {
      toast.error("Снимката не е качена");
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <input ref={input} type="file" accept={PHOTO_TYPES.join(",")} capture="environment" className="hidden" onChange={onFile} data-testid="site-photo-input" />
      <Button variant="outline" disabled={busy || !projectId} onClick={() => input.current && input.current.click()}
        className={`h-16 rounded-2xl flex-col text-xs ${className}`} data-testid="site-photo-button">
        <Camera className="w-5 h-5 mb-1 text-emerald-400" />Снимка на обекта
      </Button>
      {problem && <p className="text-xs text-red-400" role="alert" data-testid="site-photo-problem">{problem}</p>}
    </>
  );
}
