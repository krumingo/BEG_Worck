// Localization utilities for date, time, currency, and number formatting
import i18n from 'i18next';

// Get current locale based on i18n language
export const getLocale = () => {
  const lang = i18n.language || 'bg';
  return lang === 'bg' ? 'bg-BG' : 'en-US';
};

// Format date based on current language
export const formatDate = (dateStr, options = {}) => {
  if (!dateStr) return '-';
  const locale = getLocale();
  const defaultOptions = { day: '2-digit', month: 'short', year: 'numeric' };
  return new Date(dateStr).toLocaleDateString(locale, { ...defaultOptions, ...options });
};

// Format date and time
export const formatDateTime = (dateStr, options = {}) => {
  if (!dateStr) return '-';
  const locale = getLocale();
  const defaultOptions = { 
    day: '2-digit', 
    month: 'short', 
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  };
  return new Date(dateStr).toLocaleString(locale, { ...defaultOptions, ...options });
};

// Format time only
export const formatTime = (dateStr) => {
  if (!dateStr) return '-';
  const locale = getLocale();
  return new Date(dateStr).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' });
};

// Format currency
export const formatCurrency = (amount, currency = 'EUR') => {
  const locale = getLocale();
  return new Intl.NumberFormat(locale, { 
    style: 'currency', 
    currency 
  }).format(amount || 0);
};

// Canonical money formatter — ALWAYS EUR (€). Single source of truth for
// money display across the app. Optional VAT tag:
//   money(x)                 → "1 200,00 €"
//   money(x, {vat: 'incl'})  → "1 200,00 € с ДДС"
//   money(x, {vat: 'excl'})  → "1 200,00 € без ДДС"
export const money = (amount, opts = {}) => {
  const base = formatCurrency(amount, 'EUR');
  if (opts.vat === 'incl') return `${base} с ДДС`;
  if (opts.vat === 'excl') return `${base} без ДДС`;
  return base;
};

// Format number
export const formatNumber = (num, decimals = 2) => {
  if (num === null || num === undefined) return '-';
  const locale = getLocale();
  return new Intl.NumberFormat(locale, { 
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals 
  }).format(num);
};

// Format percentage
export const formatPercent = (num) => {
  if (num === null || num === undefined) return '-';
  const locale = getLocale();
  return new Intl.NumberFormat(locale, { 
    style: 'percent',
    minimumFractionDigits: 0,
    maximumFractionDigits: 2
  }).format(num / 100);
};

// Relative time formatting
export const formatRelativeTime = (dateStr) => {
  if (!dateStr) return '-';
  const locale = getLocale();
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
  const now = new Date();
  const date = new Date(dateStr);
  const diffMs = date - now;
  const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24));
  
  if (Math.abs(diffDays) < 1) {
    const diffHours = Math.round(diffMs / (1000 * 60 * 60));
    if (Math.abs(diffHours) < 1) {
      const diffMinutes = Math.round(diffMs / (1000 * 60));
      return rtf.format(diffMinutes, 'minute');
    }
    return rtf.format(diffHours, 'hour');
  }
  if (Math.abs(diffDays) < 30) {
    return rtf.format(diffDays, 'day');
  }
  if (Math.abs(diffDays) < 365) {
    return rtf.format(Math.round(diffDays / 30), 'month');
  }
  return rtf.format(Math.round(diffDays / 365), 'year');
};

export default {
  getLocale,
  formatDate,
  formatDateTime,
  formatTime,
  formatCurrency,
  formatNumber,
  formatPercent,
  formatRelativeTime,
};
