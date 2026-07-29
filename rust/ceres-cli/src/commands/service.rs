//! Commands managing the project's background service.

use std::io::Write as _;
use std::path::Path;

use crate::error::{Result, failure};
use crate::output::{Output, Table};
use crate::project::Project;
use crate::service::service_for;

/// Generate the service definition and write it to a file or stdout.
pub fn generate(project: &Project, output: &Output, path: Option<&Path>) -> Result<()> {
    let service = resolve(project, output)?;
    let definition = service.generate()?;

    match path {
        Some(path) => std::fs::write(path, &definition)
            .map_err(|error| failure!("Failed to write {}. {error}", path.display()))?,
        None => {
            let mut stdout = std::io::stdout().lock();
            let _ = stdout.write_all(&definition);
            let _ = stdout.flush();
        }
    }

    Ok(())
}

/// Create or update the service definition, then start the service.
pub fn start(project: &Project, output: &Output) -> Result<()> {
    let service = resolve(project, output)?;
    output.write(format!(
        "Starting service '{}' at '{}'...",
        service.name(),
        service.location().display()
    ));
    service.start()?;
    output.write("Service started successfully.");
    Ok(())
}

/// Stop the running service and delete its definition file.
pub fn stop(project: &Project, output: &Output) -> Result<()> {
    let service = resolve(project, output)?;
    output.write(format!(
        "Stopping service '{}' at '{}'...",
        service.name(),
        service.location().display()
    ));
    service.stop()?;
    output.write("Service stopped successfully.");
    Ok(())
}

/// Display the service name, user, state, and location in a table.
pub fn status(project: &Project, output: &Output) -> Result<()> {
    let service = resolve(project, output)?;

    let mut table = Table::new(None);
    table
        .column("Name")
        .column("User")
        .column("State")
        .column("Location");
    table.row([
        service.name(),
        service.user(),
        service.state().title().to_string(),
        service.location().display().to_string(),
    ]);
    output.write_table(&table);
    Ok(())
}

/// Build the platform service manager from the project configuration.
fn resolve(project: &Project, output: &Output) -> Result<Box<dyn crate::service::Service>> {
    let meta = project.load_meta()?;
    service_for(project.clone(), meta.service, *output)
}
