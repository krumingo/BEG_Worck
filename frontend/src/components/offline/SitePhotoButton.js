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

const PHOTO_MAX = 25 * 1024 * 1024;

export default function SitePhotoButton({ projectId, className = "" }) {
  const input = useRef(null);
  const [busy, setBusy] = useState(false);
  const onFile = async (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!file || !projectId) return;
    if (file.size > PHOTO_MAX) { toast.error("Снимката е по-голяма от 25 MB"); return; }
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
      <input ref={input} type="file" accept="image/*" capture="environment" className="hidden" onChange={onFile} data-testid="site-photo-input" />
      <Button variant="outline" disabled={busy || !projectId} onClick={() => input.current && input.current.click()}
        className={`h-16 rounded-2xl flex-col text-xs ${className}`} data-testid="site-photo-button">
        <Camera className="w-5 h-5 mb-1 text-emerald-400" />Снимка на обекта
      </Button>
    </>
  );
}
