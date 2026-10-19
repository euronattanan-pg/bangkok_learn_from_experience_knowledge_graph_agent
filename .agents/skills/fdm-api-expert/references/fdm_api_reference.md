# FDM API — Groups & Endpoints Reference

**API**: Foundational Data Manager API  
**Version**: v1  

---

## API Groups Overview

| Group | Description |
|-------|-------------|
| **AssembledProducts** | No description |
| **BomCompare** | No description |
| **BusinessUnitIpClasses** | No description |
| **BusinessUnits** | No description |
| **ChangeIdentification** | No description |
| **DPI** | No description |
| **DeviceProducts** | No description |
| **DigitalConsumersMSets** | No description |
| **DigitalConsumersSpecifications** | No description |
| **FinishedProducts** | No description |
| **Formulas** | No description |
| **Groups** | No description |
| **MSets** | mSets are manufacturing BOMs (mBOMs) that have process instructions added from DPI. |
| **Materials** | No description |
| **Navigation** | No description |
| **PubSub** | No description |
| **SapBomAsFed** | Contains endpoints that apply generically across all types of specifications, including formulas, finished products, and materials. |
| **Specifications** | Contains endpoints that apply generically across all types of specifications, including formulas, finished products, and materials. |
| **Statuses** | No description |
| **StructuredATS** | No description |
| **Users** | No description |
| **Version** | No description |

---

## AssembledProducts

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/AssembledProducts` | Return a list of all assembled products, optionally filtered by group. |
| `GET` | `/AssembledProducts/GetAllAssembledProductsOptimized` | No description |
| `PUT` | `/AssembledProducts/GroupBulk/{groupName}` | Assign a list of assembled product parts to a new group. |
| `GET` | `/AssembledProducts/Obsolete` | Return a list of assembled products that are obsolete or have an obsolete mBOM, filtered by group. |
| `GET` | `/AssembledProducts/Search/{searchValue}` | Return a list of assembled products filtered by a text value and grouped by assigned group. |
| `GET` | `/AssembledProducts/Search/{searchValue}/obsolete` | Return a list of obsolete assembled products filtered by a text value and grouped by assigned group. |
| `GET` | `/AssembledProducts/{assembledProductId}` | Return an assembled product whether it's a minor version or not. |
| `GET` | `/AssembledProducts/{assembledProductId}/Group` | Return the group an assembled product belongs to. |
| `PUT` | `/AssembledProducts/{assembledProductId}/Group` | Assign an assembled product part to a new group. |
| `GET` | `/AssembledProducts/{assembledProductId}/Status` | Return an assembled product's status. |
| `GET` | `/AssembledProducts/{assembledProductUniqueId}/minorversions` | Return all of a given assembled product's minor versions. |

## BomCompare

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/BomCompare/compare/{importDate}` | No description |
| `GET` | `/BomCompare/syncmboms/{importDate}` | No description |

## BusinessUnitIpClasses

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/BusinessUnitIpClasses` | CreateAsync a new business unit. |
| `GET` | `/BusinessUnitIpClasses/ipClasses` | Retrieves a list with all ipclasses associated with a tenant. |
| `GET` | `/BusinessUnitIpClasses/{id}` | Return a business unit with associated ipclasses. |
| `PUT` | `/BusinessUnitIpClasses/{id}` | UpdateAsync a new business unit. |
| `DELETE` | `/BusinessUnitIpClasses/{id}` | DeleteAsync a new business unit. Soft deleted (marked as inactive). |

## BusinessUnits

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/BusinessUnits` | No description |
| `GET` | `/BusinessUnits/with-ipClasses` | No description |

## ChangeIdentification

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/ChangeIdentification` | Get details for specifications of a certain type  that have been changed in a date range which are used in other specifications of certain types |
| `POST` | `/ChangeIdentification/SendEmailNotification` | Sends an email to a list of recipients with details of changed specifications in a date range |

## DPI

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/DigitalConsumers/DPI/Generic` | Sends a generic request to DPI. The body of the request is forwarded directly
to DPI. Consult DPI documentation for body formatting and possible requests and responses. |
| `POST` | `/DigitalConsumers/DPI/msets/choices` | No description |
| `POST` | `/DigitalConsumers/DPI/msets/massdownload` | No description |
| `POST` | `/DigitalConsumers/{digitalConsumer}/DPI/MRT` | Creates a new MRT in DPI using an uploaded .zip file. |
| `DELETE` | `/DigitalConsumers/{digitalConsumer}/DPI/MRT` | Deletes (or archives) an MRT currently in DPI. |

## DeviceProducts

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/DeviceProducts` | Return a list of all device products, optionally filtered by group. |
| `GET` | `/DeviceProducts/GetAllDeviceProductsOptimized` | Return a list of all device products, optionally filtered by group. |
| `PUT` | `/DeviceProducts/GroupBulk/{groupName}` | Assign a list of device product parts to a new group. |
| `GET` | `/DeviceProducts/Search/{searchValue}` | Return a list of device products filtered by a text value and grouped by assigned group. |
| `GET` | `/DeviceProducts/Search/{searchValue}/obsolete` | Returns a list of obsolete device products filtered by a search value and grouped by assigned group. |
| `GET` | `/DeviceProducts/{deviceProductId}` | Return a device product, whether it's a minor version or not. |
| `GET` | `/DeviceProducts/{deviceProductId}/Group` | Return the group a device product belongs to. |
| `GET` | `/DeviceProducts/{deviceProductId}/Status` | Return a device product's status. |
| `PUT` | `/DeviceProducts/{deviceProductUniqueId}/group` | Assign a device product to a new group. |
| `GET` | `/DeviceProducts/{deviceProductUniqueId}/minorversions` | Return all of a given device product's minor versions. |

## DigitalConsumersMSets

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/digitalconsumers/msets/mass/release` | FDM sets specifications as released for a given DigitalConsumerMSetStatus.  Only releases for mboms that have the "Available" status |
| `GET` | `/digitalconsumers/msets/rejections` | Retrieves an array of rejection messages for all mSets, which can be filtered by acknowledgement. |
| `POST` | `/digitalconsumers/msets/rejections/acknowledge/{rejectionId}` | The Digital consumer acknowledges a single rejection message on a mSet. Must pass the rejection ID received from the rejection list. |
| `GET` | `/digitalconsumers/msets/rejections/{formulaId}` | Retrieves an array of rejection messages associated with a specifc mSet, which can be filtered by acknowledgement. |
| `POST` | `/digitalconsumers/msets/rejections/{formulaId}` | The Digital Consumer sends a rejection message to be attached to the mSet, detailing why the mSet was rejected for later review. |
| `POST` | `/digitalconsumers/msets/release/{formulaId}` | FDM sets specifications as released for a given DigitalConsumerMSetStatus.  Only releases for mboms that have the "Available" status |
| `GET` | `/digitalconsumers/msets/status/{formulaId}` | Gets a list of all assigned statuses from digital consumers regardless of status. |
| `POST` | `/digitalconsumers/msets/status/{formulaId}` | The Digital Consumer sets the status for an mSet to a freeform status string, defined by the digital consumer. |
| `PUT` | `/digitalconsumers/msets/status/{formulaId}` | The Digital Consumer sets the status for an mSet to a freeform status string, defined by the digital consumer. |
| `GET` | `/digitalconsumers/msets/{digitalConsumerName}/Obsolete` | Returns a list of mset specifications that are obsolete for a given digital consumer. |
| `GET` | `/digitalconsumers/msets/{digitalConsumer}/mboms` | Retrieves all mSet mboms that are released to a certain digital consumer |
| `GET` | `/digitalconsumers/msets/{digitalConsumer}/search` | Searches to get a list of mSets based on digital consumer data. Fitlers out obsolete when searching. |
| `GET` | `/digitalconsumers/msets/{digitalConsumer}/statushistory/{formulaId}` | Gets a list of archived digital consumer statuses for an mSet including the current status for a particular digital consumer. |
| `GET` | `/digitalconsumers/msets/{digitalConsumer}/unreleased` | Retrieves all mSets that can be released to a certain digital consumer, but it does not return specifications that are obsolete. |

## DigitalConsumersSpecifications

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/DigitalConsumers/Status/{specificationId}` | Returns a list of all assigned statuses from digital consumers regardless of status. |
| `POST` | `/DigitalConsumers/mass/release` | Releases all specified mboms. |
| `GET` | `/DigitalConsumers/rejections` | Retrieves an array of rejection messages for all specifications, which can be filtered by acknowledgement. |
| `POST` | `/DigitalConsumers/rejections/acknowledge/{rejectionId}` | Acknowledges a single rejection message on a specification. |
| `GET` | `/DigitalConsumers/rejections/{specificationId}` | Retrieves an array of rejection messages associated with a specific specification, which can be filtered by acknowledgement. |
| `POST` | `/DigitalConsumers/rejections/{specificationId}` | Sends a rejection message to be attached to the specification. |
| `POST` | `/DigitalConsumers/release/{specificationId}` | Releases a single specification. Only releases "Available" status |
| `POST` | `/DigitalConsumers/resend/{specificationId}` | Re-sends a specification to a push digital consumer. Filters obsolete specifications |
| `GET` | `/DigitalConsumers/settings` | Obtain Digital Consumer settings |
| `POST` | `/DigitalConsumers/status/{specificationId}` | Sets the status for a finished product or formula to a freeform status string, defined by the digital consumer. |
| `PUT` | `/DigitalConsumers/status/{specificationId}` | Sets the status for a finished product or formula to a freeform status string, defined by the digital consumer. |
| `GET` | `/DigitalConsumers/{digitalConsumerName}/Obsolete` | Returns a list of specifications that are obsolete for a given digital consumer. |
| `GET` | `/DigitalConsumers/{digitalConsumerName}/appmboms` | No description |
| `GET` | `/DigitalConsumers/{digitalConsumerName}/fopmboms` | No description |
| `GET` | `/DigitalConsumers/{digitalConsumerName}/fpps` | No description |
| `GET` | `/DigitalConsumers/{digitalConsumer}/search` | Returns a list of specifications based on digital consumer data. Filters out obsolete when searching. |
| `GET` | `/DigitalConsumers/{digitalConsumer}/statushistory/{specificationId}` | Returns a list of archived digital consumer statuses for a specification including the current status for a particular digital consumer regardless of status. |

## FinishedProducts

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/FinishedProducts` | Return a list of all finished products, optionally filtered by group. |
| `GET` | `/FinishedProducts/GetAllOptimized` | No description |
| `PUT` | `/FinishedProducts/GroupBulk/{groupName}` | Assign a list of finished products to a new group. |
| `GET` | `/FinishedProducts/Obsolete` | Return a list of finished products that are obsolete or have an obsolete mBOM, filtered by group. |
| `GET` | `/FinishedProducts/Search/digitalConsumer/{fats}` | Return a list of digital consumers to be used in the mBOM filtered lists |
| `GET` | `/FinishedProducts/Search/{searchValue}` | Return a list of finished products filtered by a text value and grouped by assigned group. |
| `GET` | `/FinishedProducts/Search/{searchValue}/obsolete` | Return a list of obsolete finished products filtered by a text value and grouped by assigned group. |
| `GET` | `/FinishedProducts/{finishedProductId}/Group` | Return the group a finished product belongs to. |
| `PUT` | `/FinishedProducts/{finishedProductId}/Group` | Assign a finished product to a new group. |
| `GET` | `/FinishedProducts/{finishedProductId}/Status` | Return a finished product's status. |
| `GET` | `/FinishedProducts/{finishedProductUniqueId}/minor-versions` | Return all of a given finished product's minor versions. |
| `GET` | `/FinishedProducts/{finishedProductUniqueId}/minorversions` | Return all of a given finished product's minor versions. |

## Formulas

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/Formulas` | Return a list of formulas, optionally filtered by group and FDM Status. |
| `GET` | `/Formulas/GetAllOptimized` | No description |
| `PUT` | `/Formulas/GroupBulk/{groupName}` | Assign a list of formulas to a new group. |
| `GET` | `/Formulas/Obsolete` | Return a list of finished products that are obsolete or have an obsolete mBOM, filtered by group. |
| `GET` | `/Formulas/manufacturingstatuses/production` | Returns all of the manufacturing statuses that are able to create an mSet |
| `GET` | `/Formulas/search/{searchValue}` | Return a list of formulas filtered by a text value and grouped by assigned group. |
| `GET` | `/Formulas/search/{searchValue}/obsolete` | Return a list of formulas filtered by a text value and grouped by assigned group. |
| `GET` | `/Formulas/{formulaUniqueId}` | Return a fully-populated formula. |
| `GET` | `/Formulas/{formulaUniqueId}/group` | Return the group a formula belongs to. |
| `PUT` | `/Formulas/{formulaUniqueId}/group` | Assign a formula to a new group. |
| `GET` | `/Formulas/{formulaUniqueId}/minorversions` | Return all of a given formula's minor versions. |
| `POST` | `/Formulas/{formulaUniqueId}/minorversions/balance` | No description |
| `GET` | `/Formulas/{formulaUniqueId}/status` | Return a formula's status. |

## Groups

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/Groups` | Return a list of all download groups. |
| `GET` | `/Groups/AssembledProduct` | Return a list of all assembled product groups. |
| `GET` | `/Groups/AssembledProductMSet` | Return a list of all assembled product mset groups. |
| `GET` | `/Groups/DeviceProduct` | Return a list of all device product groups. |
| `GET` | `/Groups/FinishedProduct` | Return a list of all finished product groups. |
| `GET` | `/Groups/Formula` | Return a list of all formula groups. |
| `GET` | `/Groups/ObsoleteAssembledProduct` | Return a list of all obsolete assembled product groups. |
| `GET` | `/Groups/ObsoleteDeviceProduct` | Return a list of all obsolete device product groups. |
| `GET` | `/Groups/ObsoleteFinishedProduct` | Return a list of all obsolete finished product groups. |
| `GET` | `/Groups/ObsoleteFormula` | Return a list of all obsolete formula groups. |
| `GET` | `/Groups/default` | Get the default group name |
| `GET` | `/Groups/mSet` | Return a list of all mset groups. |

## MSets

> mSets are manufacturing BOMs (mBOMs) that have process instructions added from DPI.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/mSets` | Retrieves a list of all mSets that have been created from mBOMs. |
| `GET` | `/mSets/search/{searchValue}` | Return a list of mSets filtered by a text value and grouped by assigned group. |
| `PUT` | `/mSets/statuses` | Change status of all specified mSets. |
| `GET` | `/mSets/{formulaId}` | Retrieves a single populated mSet. |
| `GET` | `/mSets/{formulaId}/group` | Return the group a single mSet belongs to. |
| `PUT` | `/mSets/{formulaId}/group` | Assign a mSet to a new group. |
| `GET` | `/mSets/{formulaId}/status` | Return a mSet's status. |
| `PUT` | `/mSets/{formulaId}/status` | Change a mSet's status. |

## Materials

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/Materials` | Return all materials within FDM |

## Navigation

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/Navigation/menu` | Get the Navigation Table of enabled items to be brought back as a structure |

## PubSub

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/PubSub/update` | No description |

## SapBomAsFed

> Contains endpoints that apply generically across all types of specifications, including formulas, finished products, and materials.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/SapBomAsFed/{specificationId}` | Return the list of SapBomAsFedPart information related to the given specification. |

## Specifications

> Contains endpoints that apply generically across all types of specifications, including formulas, finished products, and materials.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/Specifications` | Download multiple Specifications from Enovia. |
| `GET` | `/Specifications/Downloads` | Return a list of download statuses. |
| `POST` | `/Specifications/Downloads/Acknowledge` | Acknowledge all failed downloads. |
| `GET` | `/Specifications/Downloads/Count` | Returns the count of items in each download status |
| `POST` | `/Specifications/Downloads/Retry` | Retrys all failed specification downloads using a single set of credentials. |
| `POST` | `/Specifications/Downloads/{id}/Acknowledge` | Acknowledge a single failed download. |
| `POST` | `/Specifications/Downloads/{id}/Retry` | Retrys a single failed specification download. |
| `GET` | `/Specifications/listbytype/{type}` | Get all specifications in a different format for a given type |
| `GET` | `/Specifications/masschange` | No description |
| `POST` | `/Specifications/populateExpiryDate` | Populate the expiry date field for mbom and msets in database |
| `GET` | `/Specifications/productcategoryplatforms/wetweight` | No description |
| `GET` | `/Specifications/search` | Search all downloaded specifications by date or type criteria. |
| `GET` | `/Specifications/tenantIpClasses` | No description |
| `POST` | `/Specifications/{identifier}` | Download a Specification from Enovia. |
| `GET` | `/Specifications/{specificationId}` | Return a fully-populated specification. |
| `GET` | `/Specifications/{specificationId}/ActionAudits` | Retreives a list of audits containing user-initiated actions. |
| `GET` | `/Specifications/{specificationId}/Changes` | Return a total list of changes for the provided specification ID and the specifications in its BOM. |
| `GET` | `/Specifications/{specificationId}/Parameters` | Return a list of a specification's local parameters. |
| `POST` | `/Specifications/{specificationId}/Parameters` | Add a new parameter to a specification. |
| `PUT` | `/Specifications/{specificationId}/Parameters` | Update an existing specification parameter. |
| `DELETE` | `/Specifications/{specificationId}/Parameters` | Delete an existing specification parameter. |
| `GET` | `/Specifications/{specificationId}/StatusDetails` | Gets the latest status information for a specification, including who set the status if manuallly changed. |
| `GET` | `/Specifications/{specificationId}/WhereUsed` | Return a total list of Finished Products and Formulas that use the provided specification. |
| `GET` | `/Specifications/{specificationId}/basic` | Return a specification with only the fields populated by GetCloudSpecification. |
| `GET` | `/Specifications/{specificationId}/performanceSpecifications` | Returns performance specifications parsed from the PerfSpecsExt document. Currently supported for FPP, APP, CUP, COP, and IP |

## Statuses

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/Statuses/Names` | Return a list of possible statuses for specifications, including local translation. |

## StructuredATS

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/StructuredATS/{specificationId}` | Get the SATS by unique id |

## Users

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/Users/Login` | Authenticates a user via LDAP and returns a JWT token for the FDM API. |
| `POST` | `/Users/LoginMFA` | Authenticates an NPA (Non-Person Account) user with MFA and returns a JWT token for the FDM API. |
| `POST` | `/Users/Logout` | Logs out the current user and audits the logout event. |
| `GET` | `/Users/ValidateAdminToken` | No description |

## Version

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Returns the application version as a string. |
| `GET` | `/name` | Returns the application instance name as a string. |
