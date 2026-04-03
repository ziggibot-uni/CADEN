use anyhow::{anyhow, Result};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MoodleCourse {
    pub id: String,
    pub name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MoodleAssignment {
    pub id: String,
    pub title: String,
    pub course_name: String,
    pub due_date: Option<String>,
    pub submitted: bool,
    pub url: String,
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

    /// Fetch all courses the current user is enrolled in.
    pub async fn get_enrolled_courses(&self) -> Result<Vec<MoodleCourse>> {
        let site = self.call("core_webservice_get_site_info", HashMap::new()).await?;
        let user_id = site["userid"].as_i64().unwrap_or(0).to_string();
        let mut params = HashMap::new();
        params.insert("userid", user_id.as_str());
        let resp = self.call("core_enrol_get_users_courses", params).await?;
        let mut courses = Vec::new();
        if let Some(arr) = resp.as_array() {
            for c in arr {
                let id = c["id"].as_i64().unwrap_or_default().to_string();
                let name = c["fullname"].as_str().unwrap_or("").to_string();
                if !name.is_empty() {
                    courses.push(MoodleCourse { id, name });
                }
            }
        }
        Ok(courses)
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

    /// Fetch upcoming assignment deadlines.
    /// Runs both APIs and merges: mod_assign for the full list, calendar for completion status.
    pub async fn fetch_assignments(&self) -> Result<Vec<MoodleAssignment>> {
        // Always get the full assignment list from mod_assign (universally available)
        let mut assignments = self.fetch_via_assignments_api().await.unwrap_or_default();

        // Supplement with completion status from calendar action events if available
        if let Ok(cal_events) = self.fetch_via_calendar_api().await {
            // Build a map of calendar event id → submitted status
            // Calendar events use the assignment cmid/instance as their instance field,
            // but their id differs from the assign id. Match by title as a heuristic,
            // or just mark calendar-only items as additional entries.
            // Simplest: for any assignment already in the list, check if it appears
            // in cal_events as completed (itemcount==0).
            use std::collections::HashSet;
            let completed_titles: HashSet<String> = cal_events
                .iter()
                .filter(|e| e.submitted)
                .map(|e| e.title.clone())
                .collect();

            for a in &mut assignments {
                if completed_titles.contains(&a.title) {
                    a.submitted = true;
                }
            }

            // Also add any calendar events not already covered by mod_assign
            let existing_titles: HashSet<String> =
                assignments.iter().map(|a| a.title.clone()).collect();
            for ev in cal_events {
                if !existing_titles.contains(&ev.title) {
                    assignments.push(ev);
                }
            }
        }

        Ok(assignments)
    }

    async fn fetch_via_calendar_api(&self) -> Result<Vec<MoodleAssignment>> {
        // core_calendar_get_calendar_upcoming_view is what Moodle shows natively
        // as the upcoming events view — no time params needed, returns all upcoming events.
        let resp = self
            .call("core_calendar_get_calendar_upcoming_view", HashMap::new())
            .await?;

        let mut assignments: Vec<MoodleAssignment> = Vec::new();

        if let Some(events) = resp["events"].as_array() {
            for event in events {
                // Accept all module types — upcoming view already curates relevance
                let id = event["id"].as_i64().unwrap_or_default().to_string();
                let title = event["activityname"]
                    .as_str()
                    .or_else(|| event["name"].as_str())
                    .unwrap_or("")
                    .trim_end_matches(" is due")
                    .to_string();
                let course_name = event["course"]["fullname"]
                    .as_str()
                    .or_else(|| event["course"]["shortname"].as_str())
                    .unwrap_or("")
                    .to_string();
                let due_ts = event["timestart"].as_i64().filter(|&t| t > 0);
                let due_date = due_ts.map(|ts| {
                    chrono::DateTime::from_timestamp(ts, 0)
                        .unwrap_or_default()
                        .to_rfc3339()
                });
                let url = event["url"].as_str().unwrap_or("").to_string();
                let item_count = event["action"]["itemcount"].as_i64().unwrap_or(1);
                let submitted = item_count == 0;

                assignments.push(MoodleAssignment {
                    id,
                    title,
                    course_name,
                    due_date,
                    submitted,
                    url,
                });
            }
        }

        Ok(assignments)
    }

    async fn fetch_via_assignments_api(&self) -> Result<Vec<MoodleAssignment>> {
        let resp = self
            .call("mod_assign_get_assignments", HashMap::new())
            .await?;

        let cutoff = chrono::Utc::now().timestamp() - 86400; // yesterday
        let mut assignments: Vec<MoodleAssignment> = Vec::new();

        if let Some(courses) = resp["courses"].as_array() {
            for course in courses {
                let course_name = course["fullname"].as_str().unwrap_or("").to_string();

                if let Some(assigns) = course["assignments"].as_array() {
                    for assign in assigns {
                        let assign_id = assign["id"].as_i64().unwrap_or_default();
                        let cmid = assign["cmid"].as_i64().unwrap_or_default();
                        let title = assign["name"].as_str().unwrap_or("").to_string();
                        let due_ts = assign["duedate"].as_i64().unwrap_or(0);

                        // Skip if no due date or due more than a day ago
                        if due_ts > 0 && due_ts < cutoff {
                            continue;
                        }

                        let due_date = if due_ts > 0 {
                            chrono::DateTime::from_timestamp(due_ts, 0)
                                .map(|d| d.to_rfc3339())
                        } else {
                            None
                        };

                        let url = format!(
                            "{}/mod/assign/view.php?id={}",
                            self.base_url, cmid
                        );

                        assignments.push(MoodleAssignment {
                            id: assign_id.to_string(),
                            title,
                            course_name: course_name.clone(),
                            due_date,
                            submitted: false, // no per-assignment API call; user marks done manually
                            url,
                        });
                    }
                }
            }
        }

        Ok(assignments)
    }

    /// Returns raw JSON from a Moodle API call — used for debugging sync issues.
    pub async fn debug_fetch(&self, wsfunction: &str) -> Result<serde_json::Value> {
        self.call(wsfunction, HashMap::new()).await
    }
}
