import { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import DashboardLayout from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import {
  ArrowLeft,
  MapPin,
  User,
  Building2,
  Phone,
  Hash,
  Camera,
  Upload,
  Trash2,
  Loader2,
  Image as ImageIcon,
  X,
  Calendar,
  Pencil,
  Save,
} from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

const STATUS_CONFIG = {
  Active: { label: "Активен", color: "bg-green-500/20 text-green-400 border-green-500/30" },
  Paused: { label: "Пауза", color: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30" },
  Finished: { label: "Завършен", color: "bg-blue-500/20 text-blue-400 border-blue-500/30" },
  Archived: { label: "Архив", color: "bg-gray-500/20 text-gray-400 border-gray-500/30" },
};

export default function SiteDetailPage() {
  const { siteId } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const fileInputRef = useRef(null);

  const [site, setSite] = useState(null);
  const [photos, setPhotos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [selectedPhoto, setSelectedPhoto] = useState(null);
  const [isEditing, setIsEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editData, setEditData] = useState({});

  const token = localStorage.getItem("bw_token");

  // Fetch site details
  const fetchSite = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/sites/${siteId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("Site not found");
      const data = await res.json();
      setSite(data);
      setEditData({
        name: data.name,
        address_text: data.address_text,
        status: data.status,
        notes: data.notes || "",
      });
    } catch (err) {
      toast.error("Обектът не е намерен");
      navigate("/sites");
    }
  }, [siteId, token, navigate]);

  // Fetch photos
  const fetchPhotos = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/sites/${siteId}/photos`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setPhotos(data);
      }
    } catch (err) {
      console.error("Failed to fetch photos:", err);
    }
  }, [siteId, token]);

  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      await fetchSite();
      await fetchPhotos();
      setLoading(false);
    };
    loadData();
  }, [fetchSite, fetchPhotos]);

  // Upload photo
  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Validate file type
    if (!file.type.startsWith("image/")) {
      toast.error("Моля, изберете изображение");
      return;
    }

    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("note", "");

      const res = await fetch(`${API}/api/sites/${siteId}/photos`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail?.message || err.detail || "Upload failed");
      }

      const newPhoto = await res.json();
      setPhotos((prev) => [newPhoto, ...prev]);
      toast.success("Снимката е качена");
    } catch (err) {
      toast.error(err.message);
    } finally {
      setUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  // Delete photo
  const handleDeletePhoto = async (photoId) => {
    if (!window.confirm("Сигурни ли сте, че искате да изтриете тази снимка?")) {
      return;
    }

    try {
      const res = await fetch(`${API}/api/sites/photos/${photoId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Delete failed");
      }

      setPhotos((prev) => prev.filter((p) => p.id !== photoId));
      setSelectedPhoto(null);
      toast.success("Снимката е изтрита");
    } catch (err) {
      toast.error(err.message);
    }
  };

  // Save edits
  const handleSave = async () => {
    setSaving(true);
    try {
      const res = await fetch(`${API}/api/sites/${siteId}`, {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(editData),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Save failed");
      }

      const updated = await res.json();
      setSite(updated);
      setIsEditing(false);
      toast.success("Промените са запазени");
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  };

  // Format date
  const formatDate = (isoString) => {
    if (!isoString) return "";
    const date = new Date(isoString);
    return date.toLocaleDateString("bg-BG", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  if (loading) {
    return (
      <DashboardLayout>
        <div className="flex items-center justify-center h-96">
          <Loader2 className="w-8 h-8 animate-spin text-yellow-500" />
        </div>
      </DashboardLayout>
    );
  }

  if (!site) return null;

  return (
    <DashboardLayout>
      <div className="p-4 md:p-6 space-y-6" data-testid="site-detail-page">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate("/sites")}
              className="text-gray-400 hover:text-white"
            >
              <ArrowLeft className="w-4 h-4 mr-2" />
              Обекти
            </Button>
          </div>
          <div className="flex items-center gap-2">
            {isEditing ? (
              <>
                <Button
                  variant="outline"
                  onClick={() => setIsEditing(false)}
                  className="border-gray-600"
                >
                  Отказ
                </Button>
                <Button
                  onClick={handleSave}
                  disabled={saving}
                  className="bg-yellow-500 hover:bg-yellow-600 text-black"
                >
                  {saving ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Save className="w-4 h-4 mr-2" />}
                  Запази
                </Button>
              </>
            ) : (
              <Button
                onClick={() => setIsEditing(true)}
                variant="outline"
                className="border-gray-600"
              >
                <Pencil className="w-4 h-4 mr-2" />
                Редактирай
              </Button>
            )}
          </div>
        </div>

        {/* Site Info Card */}
        <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-6">
          {isEditing ? (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label>Име на обекта</Label>
                <Input
                  value={editData.name}
                  onChange={(e) => setEditData({ ...editData, name: e.target.value })}
                  className="bg-gray-700 border-gray-600"
                />
              </div>
              <div className="space-y-2">
                <Label>Адрес</Label>
                <Textarea
                  value={editData.address_text}
                  onChange={(e) => setEditData({ ...editData, address_text: e.target.value })}
                  className="bg-gray-700 border-gray-600"
                  rows={2}
                />
              </div>
              <div className="space-y-2">
                <Label>Статус</Label>
                <Select
                  value={editData.status}
                  onValueChange={(val) => setEditData({ ...editData, status: val })}
                >
                  <SelectTrigger className="bg-gray-700 border-gray-600">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-gray-800 border-gray-700">
                    {Object.entries(STATUS_CONFIG).map(([status, config]) => (
                      <SelectItem key={status} value={status}>
                        {config.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Бележки</Label>
                <Textarea
                  value={editData.notes}
                  onChange={(e) => setEditData({ ...editData, notes: e.target.value })}
                  className="bg-gray-700 border-gray-600"
                  rows={3}
                />
              </div>
            </div>
          ) : (
            <>
              <div className="flex items-start justify-between mb-4">
                <div>
                  <h1 className="text-2xl font-bold text-white mb-2">{site.name}</h1>
                  <Badge className={STATUS_CONFIG[site.status]?.color || ""}>
                    {STATUS_CONFIG[site.status]?.label || site.status}
                  </Badge>
                </div>
              </div>

              <div className="grid md:grid-cols-2 gap-4 text-sm">
                <div className="flex items-start gap-3 text-gray-300">
                  <MapPin className="w-5 h-5 text-gray-400 mt-0.5 flex-shrink-0" />
                  <span>{site.address_text}</span>
                </div>

                <div className="flex items-center gap-3 text-gray-300">
                  {site.owner_type === "person" ? (
                    <User className="w-5 h-5 text-gray-400" />
                  ) : (
                    <Building2 className="w-5 h-5 text-gray-400" />
                  )}
                  <span>{site.owner_name}</span>
                </div>

                <div className="flex items-center gap-3 text-gray-300">
                  {site.owner_type === "person" ? (
                    <Phone className="w-5 h-5 text-gray-400" />
                  ) : (
                    <Hash className="w-5 h-5 text-gray-400" />
                  )}
                  <span>{site.owner_identifier}</span>
                </div>

                <div className="flex items-center gap-3 text-gray-300">
                  <Calendar className="w-5 h-5 text-gray-400" />
                  <span>Създаден: {formatDate(site.created_at)}</span>
                </div>
              </div>

              {site.notes && (
                <div className="mt-4 pt-4 border-t border-gray-700">
                  <p className="text-gray-400 text-sm">{site.notes}</p>
                </div>
              )}
            </>
          )}
        </div>

        {/* Photos Section */}
        <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <Camera className="w-5 h-5" />
              Снимки ({photos.length})
            </h2>
            <div>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                capture="environment"
                onChange={handleUpload}
                className="hidden"
                id="photo-upload"
              />
              <Button
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
                className="bg-yellow-500 hover:bg-yellow-600 text-black"
                data-testid="upload-photo-btn"
              >
                {uploading ? (
                  <Loader2 className="w-4 h-4 animate-spin mr-2" />
                ) : (
                  <Upload className="w-4 h-4 mr-2" />
                )}
                Качи снимка
              </Button>
            </div>
          </div>

          {photos.length === 0 ? (
            <div className="text-center py-12 text-gray-400">
              <ImageIcon className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p>Няма качени снимки</p>
              <p className="text-sm mt-2">Натиснете "Качи снимка" за да добавите</p>
            </div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
              {photos.map((photo) => (
                <div
                  key={photo.id}
                  className="relative group cursor-pointer"
                  onClick={() => setSelectedPhoto(photo)}
                  data-testid={`photo-${photo.id}`}
                >
                  <div className="aspect-square bg-gray-700 rounded-lg overflow-hidden">
                    <img
                      src={`${API}${photo.url}`}
                      alt=""
                      className="w-full h-full object-cover transition-transform group-hover:scale-105"
                      loading="lazy"
                    />
                  </div>
                  <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity rounded-lg flex items-end p-2">
                    <div className="text-xs text-white truncate">
                      {formatDate(photo.uploaded_at)}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Photo Lightbox */}
        <Dialog open={!!selectedPhoto} onOpenChange={() => setSelectedPhoto(null)}>
          <DialogContent className="bg-gray-900 border-gray-700 text-white max-w-4xl p-0">
            {selectedPhoto && (
              <>
                <div className="relative">
                  <img
                    src={`${API}${selectedPhoto.url}`}
                    alt=""
                    className="w-full max-h-[70vh] object-contain"
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setSelectedPhoto(null)}
                    className="absolute top-2 right-2 bg-black/50 hover:bg-black/70"
                  >
                    <X className="w-5 h-5" />
                  </Button>
                </div>
                <div className="p-4 flex items-center justify-between border-t border-gray-700">
                  <div className="text-sm text-gray-400">
                    <p>Качена от: {selectedPhoto.uploader_name}</p>
                    <p>{formatDate(selectedPhoto.uploaded_at)}</p>
                    {selectedPhoto.note && <p className="mt-1">{selectedPhoto.note}</p>}
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleDeletePhoto(selectedPhoto.id)}
                    className="text-red-400 hover:text-red-300 hover:bg-red-900/20"
                  >
                    <Trash2 className="w-4 h-4 mr-2" />
                    Изтрий
                  </Button>
                </div>
              </>
            )}
          </DialogContent>
        </Dialog>
      </div>
    </DashboardLayout>
  );
}
