use anyhow::{anyhow, Result};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MoodleAssignment {
    pub id: String,
    pub title: String,
    pub course_name: String,
    pub due_date: Option<String>,
    pub submitted: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MoodleEvent {
    pub id: String,
    pub title: String,
    pub course_name: String,
    pub due_date: Option<String>,
    pub event_type: String,
}

#[derive(Clone)]
pub struct MoodleClient {
    base_url: String,
    token: String,
    client: Client,
}

impl MoodleClient {
    pub fn new(base_url: String, token: String) -> Self {
        Self {
            base_url: base_url.trim_end_matches('/').to_string(),
            token,
            client: Client::builder()
                .timeout(std::time::Duration::from_secs(30))
                .build()
                .unwrap_or_default(),
        }
    }

    fn endpoint(&self) -> String {
        format!("{}/webservice/rest/server.php", self.base_url)
    }

    async fn call(&self, wsfunction: &str, params: HashMap<&str, &str>) -> Result<serde_json::Value> {
        let mut form: Vec<(String, String)> = vec![
            ("wstoken".to_string(), self.token.clone()),
            ("wsfunction".to_string(), wsfunction.to_string()),
            ("moodlewsrestformat".to_string(), "json".to_string()),
        ];
        for (k, v) in params {
            form.push((k.to_string(), v.to_string()));
        }

        let resp = self
            .client
            .post(&self.endpoint())
            .form(&form)
            .send()
            .await?;

        if !resp.status().is_success() {
            return Err(anyhow!("Moodle API error: {}", resp.status()));
        }

        let body: serde_json::Value = resp.json().await?;

        // Moodle returns errors inside the JSON body
        if let Some(exc) = body.get("exception") {
            let msg = body["message"].as_str().unwrap_or("Unknown Moodle error");
            return Err(anyhow!("Moodle error ({}): {}", exc, msg));
        }

        Ok(body)
    }

    /// Test connection — calls core_webservice_get_site_info.
    pub async fn test_connection(&self) -> Result<String> {
        let resp = self
            .call("core_webservice_get_site_info", HashMap::new())
            .await?;
        let site_name = resp["sitename"].as_str().unwrap_or("Moodle").to_string();
        Ok(site_name)
    }

    /// Fetch upcoming events from the calendar.
    pub async fn fetch_upcoming_events(&self) -> Result<Vec<MoodleEvent>> {
        let params = HashMap::new();
        let resp = self
            .call("core_calendar_get_calendar_upcoming_view", params)
            .await?;

        let mut events: Vec<MoodleEvent> = Vec::new();

        if let Some(items) = resp["events"].as_array() {
            for item in items {
                let id = item["id"].as_i64().unwrap_or_default().to_string();
                let title = item["name"].as_str().unwrap_or("(no title)").to_string();
                let course_name = item["course"]["fullname"]
                    .as_str()
                    .unwrap_or("")
                    .to_string();
                let event_type = item["eventtype"].as_str().unwrap_or("").to_string();

                // Due date is a Unix timestamp
                let due_date = item["timestart"].as_i64().map(|ts| {
                    chrono::DateTime::from_timestamp(ts, 0)
                        .unwrap_or_default()
                        .to_rfc3339()
                });

                events.push(MoodleEvent {
                    id,
                    title,
                    course_name,
                    due_date,
                    event_type,
                });
            }
        }

        Ok(events)
    }

    /// Fetch assignments for all enrolled courses.
    pub async fn fetch_assignments(&self) -> Result<Vec<MoodleAssignment>> {
        let resp = self
            .call("mod_assign_get_assignments", HashMap::new())
            .await?;

        let mut assignments: Vec<MoodleAssignment> = Vec::new();

        if let Some(courses) = resp["courses"].as_array() {
            for course in courses {
                let course_name = course["fullname"].as_str().unwrap_or("").to_string();
                let course_id = course["id"].as_i64().unwrap_or_default();

                if let Some(assigns) = course["assignments"].as_array() {
                    for assign in assigns {
                        let assign_id = assign["id"].as_i64().unwrap_or_default();
                        let title = assign["name"].as_str().unwrap_or("").to_string();
                        let due_ts = assign["duedate"].as_i64().filter(|&t| t > 0);
                        let due_date = due_ts.map(|ts| {
                            chrono::DateTime::from_timestamp(ts, 0)
                                .unwrap_or_default()
                                .to_rfc3339()
                        });

                        // Check submission status
                        let submitted = self
                            .check_submission_status(assign_id, course_id)
                            .await
                            .unwrap_or(false);

                        assignments.push(MoodleAssignment {
                            id: assign_id.to_string(),
                            title,
                            course_name: course_name.clone(),
                            due_date,
                            submitted,
                        });
                    }
                }
            }
        }

        Ok(assignments)
    }

    async fn check_submission_status(&self, assign_id: i64, _course_id: i64) -> Result<bool> {
        let assign_id_str = assign_id.to_string();
        let mut params = HashMap::new();
        params.insert("assignid", assign_id_str.as_str());

        let resp = self
            .call("mod_assign_get_submission_status", params)
            .await?;

        // Check if there's a submitted submission
        let status = resp["lastattempt"]["submission"]["status"]
            .as_str()
            .unwrap_or("");
        Ok(status == "submitted")
    }
}
