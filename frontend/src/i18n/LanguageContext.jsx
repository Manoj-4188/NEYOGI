import React, { createContext, useContext, useState } from 'react';
import { translations } from './translations.js';

const LanguageContext = createContext();

export function LanguageProvider({ children }) {
  const [lang, setLang] = useState('en');

  const toggleLang = () => {
    setLang((prev) => (prev === 'en' ? 'kn' : 'en'));
  };

  const t = translations[lang];

  return (
    <LanguageContext.Provider value={{ lang, setLang, toggleLang, t }}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useLanguage() {
  const context = useContext(LanguageContext);
  if (!context) {
    return { lang: 'en', toggleLang: () => {}, t: translations.en };
  }
  return context;
}
