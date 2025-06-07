"use client";

import React, { useState } from "react";
import styles from "./page.module.css"; 

export default function HomePage() {
  const [url, setUrl] = useState("");
  const [clonedHtml, setClonedHtml] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsLoading(true);
    setClonedHtml("");
    setError(null);

    try {
      const response = await fetch("http://localhost:8000/api/clone", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ url }),
      });

      // Check for HTTP errors
      if (!response.ok) {
        // Try to get a detailed error message from the backend
        const errorData = await response.json();
        throw new Error(errorData.detail || "An unknown error occurred.");
      }

      const data = await response.json();
      setClonedHtml(data.html_content);

    } catch (err: any) {
      console.error("Failed to clone website:", err);
      setError(err.message || "Failed to connect to the backend.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <main className={styles.container}>
      <div className={styles.contentWrapper}>
        <h1>Orchids Website Cloner</h1>
        
        <form className={styles.form} onSubmit={handleSubmit}>
          <input
            className={styles.input}
            type="url"
            placeholder="Enter website URL"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={isLoading}
          />
          <button
            className={styles.button}
            type="submit"
            disabled={isLoading}
          >
            <span>{isLoading ? "Cloning..." : "Clone Website"}</span>
          </button>
        </form>

        {isLoading && (
          <div className={styles.loader}>
            <p>Please wait, the AI is working its magic...</p>
          </div>
        )}

        {error && (
          <div className={styles.error}>
            <p>Error: {error}</p>
          </div>
        )}

      </div>

      {clonedHtml && !isLoading && (
        <div className={styles.iframeContainer}>
          <iframe
            srcDoc={clonedHtml}
            title="Cloned Website Preview"
            className={styles.iframe}
            sandbox="allow-scripts allow-same-origin" // Security sandbox for iframe
          />
        </div>
      )}
    </main>
  );
}
