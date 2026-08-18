# Requirements

## Project: PeriScribe

This is a tool for systematic gathering and symbolizing of fire geography for use in fire behavior analysis and presentation.

Fire geography is pulled from configurable data sources at regular time intervals, symbolized in a way that indicates the growth of fires over time, and then made available in KML files. Each fire has a point associated with it (e.g., with a flame icon as a symbol) and a perimeter (a set of polygons) for each day that the fire is actively mapped. When there is more than one perimeter for a fire on a given day, the latest perimeter for that day is used.

## Notifications

When the output KML files are updated, a notification is sent to a configurable list of recipients. The notification includes a description of changes.

## Configuration

### Data Sources and Notification Recipients

A JSON file contains a list of notification recipients. Each recipient has properties indicating how to send the notification (email? text message? other?) and when (e.g., Any perimeter grew by a certain percentage or number of acres? Update to a fire that started in the last day and is over a certain number of acres?).

### Symbolization

There is a template file in KML format. It contains a fictional point location and a set of fictional perimeters for a single fictional fire. The location of those geographic elements do not matter. The point is named "Point Location". The latest perimeter is named "Perimeter (current)", the previous "Perimeter (old 1)", the one before that "Perimeter (old 2)", and so on ("Perimeter (current)" is required and any number of "Perimeter (old #)" templates can be present). When symbolizing real fire data, the styles associated with the fictional fire are used. This allows Google Earth, or other KML tools, to be used as the UI for specifying symbolization.

### Cached Data Location

This might be an object store like Amazon S3, an SFTP server at a web host, or a local file system (idea: use rclone to enable many different kinds of data stores without having to implement them?).

### KML Output Location

This might be an object store like Amazon S3, an SFTP server at a web host, or a local file system (idea: use rclone to enable many different kinds of data stores without having to implement them?).
